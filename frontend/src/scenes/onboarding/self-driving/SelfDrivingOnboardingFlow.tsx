import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { cn } from 'lib/utils/css-classes'

// Deliberate self-driving → legacy import: onboardingLogic owns the completion flow (marking the
// team onboarded, redirecting out) for both variants.
import { onboardingLogic } from '../legacy/onboardingLogic'
import { onboardingEventUsageLogic, type SelfDrivingOnboardingStepId } from '../onboardingEventUsageLogic'
import type { SelfDrivingGoal } from './goals'
import { goalSelectionLogic } from './goalSelectionLogic'
import { productEnablementStepLogic } from './productEnablementStepLogic'
import { RoughMark } from './RoughMark'
import { AIObservabilityStep } from './steps/AIObservabilityStep'
import { AuthorizedUrlsStep } from './steps/AuthorizedUrlsStep'
import { BillingStep } from './steps/BillingStep'
import { GoalsStep } from './steps/GoalsStep'
import { InstallStep } from './steps/InstallStep'
import { AnalyticsStep, ErrorTrackingStep, ReplayStep } from './steps/ProductEnablementSteps'
import { WelcomeStep } from './steps/WelcomeStep'

/**
 * The self-driving onboarding: run the wizard, turn on the built-in signal sources, pick a plan,
 * land in the inbox.
 *
 * The wizard's `self-driving` program does the repo-side configuration — GitHub, signal sources,
 * scouts. Team-level tool opt-ins (session replay, error tracking) live here instead: the wizard's
 * API key deliberately never gets the product_enablement scope, so the app is the only place that
 * turns tools on. Everything else this flow shows — the command, the run's progress, payment — it
 * streams rather than owns.
 */

interface StepDef {
    id: SelfDrivingOnboardingStepId
    title: string
    Content: (props: { onContinue: () => void; onSkip: () => void; completing: boolean }) => JSX.Element
    skippable?: boolean
    /** Step provides its own primary action (e.g. plan picks), so suppress the footer Continue. */
    hideContinue?: boolean
    /** Tailwind `max-w-*` for the card on this step. Defaults to `max-w-xl`; wider steps (e.g. billing
     * with side-by-side plan cards) opt into more room. */
    maxWidth?: string
}

const ANALYTICS_STEP: StepDef = { id: 'analytics', title: '', Content: AnalyticsStep, hideContinue: true }
const REPLAY_STEP: StepDef = { id: 'replay', title: '', Content: ReplayStep, hideContinue: true }
const ERROR_TRACKING_STEP: StepDef = { id: 'error-tracking', title: '', Content: ErrorTrackingStep, hideContinue: true }
const AUTHORIZED_URLS_STEP: StepDef = {
    id: 'authorized-urls',
    title: 'Add your website URLs',
    Content: AuthorizedUrlsStep,
    hideContinue: true,
}
const AI_OBSERVABILITY_STEP: StepDef = {
    id: 'ai-observability',
    title: 'Instrument your AI app',
    Content: AIObservabilityStep,
    hideContinue: true,
    maxWidth: 'max-w-2xl',
}

/** The tool steps each goal needs to reach its finish line - nothing more. */
function goalToolSteps(goal: SelfDrivingGoal | null): StepDef[] {
    switch (goal) {
        case 'user_behavior':
            return [ANALYTICS_STEP, REPLAY_STEP]
        case 'fix_issues':
            return [ERROR_TRACKING_STEP, REPLAY_STEP]
        case 'website_traffic':
            // Web analytics needs at least one authorized URL before its dashboard (the goal's
            // finish line) can show anything.
            return [AUTHORIZED_URLS_STEP]
        case 'ai_app':
            // The generic wizard install doesn't wire LLM instrumentation - without this step the
            // goal (first AI traces) is unreachable.
            return [AI_OBSERVABILITY_STEP]
        default:
            return [ANALYTICS_STEP, REPLAY_STEP, ERROR_TRACKING_STEP]
    }
}

/**
 * Say what this is, run the wizard, turn on the sources the wizard can't, pick a plan. The wizard
 * does the repo-side configuration (sources, scouts, GitHub); the team-level opt-ins are enabled
 * here because only the signed-in app carries the product_enablement scope.
 */
function buildSteps(goal: SelfDrivingGoal | null): StepDef[] {
    return [
        { id: 'welcome', title: '', Content: WelcomeStep },
        // One declared goal so the rest of the flow can drive toward it. Picking a card advances;
        // "set up everything" is the step's skip.
        {
            id: 'goals',
            title: 'What do you want to get done first?',
            Content: GoalsStep,
            hideContinue: true,
            maxWidth: 'max-w-2xl',
        },
        { id: 'install', title: 'Install PostHog', Content: InstallStep },
        // The declared goal FILTERS the tool steps: only what serves the goal gets a screen, so
        // the user reaches their finish line as fast as possible - everything else is cross-sell
        // for later, outside onboarding. No goal ("set up everything") keeps the full set. These
        // steps render their own title and a single action zone, so the flow's header title and
        // footer are suppressed.
        ...goalToolSteps(goal),
        {
            id: 'billing',
            title: 'Pick a plan',
            Content: BillingStep,
            hideContinue: true,
            maxWidth: 'max-w-3xl',
        },
    ]
}

// The card: chrome (sm+ panel; full-bleed on mobile) plus the content flex-column. Width varies per
// step via StepDef.maxWidth — SelfDrivingOnboarding just provides the backdrop + logo.
const CARD_CLASSES =
    'relative w-full flex flex-col gap-5 overflow-hidden p-0 sm:max-h-[calc(100dvh-7rem)] sm:p-8 md:p-10 sm:bg-[#f6f5f0] sm:rounded-2xl sm:shadow-[0_16px_40px_rgb(30_50_10_/_25%)] sm:border sm:border-primary'

export function SelfDrivingOnboardingFlow(): JSX.Element {
    // Mounted for the whole flow so the goal step's fire-and-forget auto-enable calls outlive the
    // step that fired them.
    useMountedLogic(productEnablementStepLogic)
    const { completeSelfDrivingOnboarding } = useActions(onboardingLogic)
    const { isCompleting } = useValues(onboardingLogic)
    const {
        reportSelfDrivingOnboardingStarted,
        reportSelfDrivingOnboardingStepViewed,
        reportSelfDrivingOnboardingStepCompleted,
        reportSelfDrivingOnboardingStepSkipped,
    } = useActions(onboardingEventUsageLogic)
    // The step list depends on the declared goal (persisted, so a refresh keeps the conditional
    // steps in place).
    const { selectedGoal } = useValues(goalSelectionLogic)
    const steps = useMemo(() => buildSteps(selectedGoal), [selectedGoal])
    // Track the current step by id, not index, so goal changes (which insert/remove steps) can't
    // shift the user onto a different step. Initialize from the URL so a refresh — or an OAuth
    // callback that lands back on ?step=install (e.g. the GitHub connect flow) — resumes where it
    // left off instead of restarting at welcome.
    const [stepId, setStepId] = useState<SelfDrivingOnboardingStepId>(() => {
        const fromUrl = steps.find((s) => s.id === router.values.searchParams['step'])
        return fromUrl?.id ?? 'welcome'
    })

    // If the current step left the list (e.g. the goal changed and removed it), fall back to the
    // start rather than rendering nothing.
    const stepIndex = Math.max(
        0,
        steps.findIndex((s) => s.id === stepId)
    )
    const step = steps[stepIndex]
    const isFirst = stepIndex === 0
    const isLast = stepIndex === steps.length - 1

    // Funnel (GROW-89): `started` fires once per fresh entry — a ?step= resume (refresh, OAuth
    // callback) is a continuation, not a new start. `step viewed` fires for every step shown,
    // including the one this mounts on.
    useOnMountEffect(() => {
        if (stepIndex === 0) {
            reportSelfDrivingOnboardingStarted()
        }
    })
    useEffect(() => {
        reportSelfDrivingOnboardingStepViewed(step.id)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [step.id, reportSelfDrivingOnboardingStepViewed])

    // Keep ?step= in sync as the user moves so the URL stays resumable, preserving any other params
    // (like the integration ids the GitHub callback appends).
    const goToStep = (index: number): void => {
        const target = steps[index]
        if (!target) {
            return
        }
        setStepId(target.id)
        router.actions.replace(router.values.location.pathname, {
            ...router.values.searchParams,
            step: target.id,
        })
    }

    const advance = (): void => {
        if (isLast) {
            // Marks onboarding complete (credits the sources turned on, plus the declared goal's
            // product) and navigates out, so sceneLogic doesn't bounce the user back into onboarding.
            completeSelfDrivingOnboarding(selectedGoal)
            return
        }
        goToStep(stepIndex + 1)
    }
    // Leaving a step forward is either completing it (Continue / the step's own primary action,
    // e.g. a queued cloud run or a plan pick) or skipping it — reported separately so the funnel
    // can tell drop-off from opt-out.
    const completeStep = (): void => {
        reportSelfDrivingOnboardingStepCompleted(step.id)
        advance()
    }
    const skipStep = (): void => {
        reportSelfDrivingOnboardingStepSkipped(step.id)
        advance()
    }
    const goBack = (): void => goToStep(Math.max(0, stepIndex - 1))

    return (
        // This div is the card: chrome + per-step width. On sm+ it's capped to the viewport so the middle
        // scrolls internally; on mobile the chrome drops and content flows (the page scrolls).
        <div className={cn(CARD_CLASSES, step.maxWidth ?? 'max-w-xl')}>
            {/* Pinned header: back button + progress share one row. Equal-width side slots keep the
                progress dots centered in the card regardless of whether the back button is shown. */}
            <div className="shrink-0 flex flex-col items-center gap-4">
                <div className="flex items-center gap-2 w-full">
                    <div className="w-8 shrink-0 flex justify-start">
                        {!isFirst && (
                            <LemonButton
                                icon={<IconArrowLeft />}
                                size="small"
                                onClick={goBack}
                                tooltip="Go back"
                                aria-label="Go back"
                            />
                        )}
                    </div>
                    <div
                        className="flex-1 flex items-center justify-center gap-1.5"
                        role="group"
                        aria-label={`Step ${stepIndex + 1} of ${steps.length}`}
                    >
                        {steps.map((s, i) => (
                            <div
                                key={s.id}
                                className={`h-1.5 rounded-full transition-all ${
                                    i === stepIndex ? 'w-6 bg-accent' : 'w-1.5 bg-border'
                                }`}
                            />
                        ))}
                    </div>
                    <div className="w-8 shrink-0" />
                </div>
                {step.title && (
                    <h1 className="text-2xl font-bold text-center m-0">
                        {/* The hand-drawn squiggle from the website's section headers - only on the
                            goals step, where the question is the hero. Keyed by title so the
                            annotation is redrawn at the text's width (it only measures on mount). */}
                        {step.id === 'goals' ? (
                            <RoughMark key={step.title} type="underline" color="#f54e00" padding={4}>
                                {step.title}
                            </RoughMark>
                        ) : (
                            step.title
                        )}
                    </h1>
                )}
            </div>

            {/* Scrollable middle: fade edges + hover scrollbar so tall steps don't hard-crop. */}
            <ScrollableShadows direction="vertical" styledScrollbars className="flex-1 min-h-0" contentClassName="px-1">
                <step.Content onContinue={completeStep} onSkip={skipStep} completing={isLast && isCompleting} />
            </ScrollableShadows>

            {/* Pinned footer — omitted when the step has neither Skip nor a footer Continue (it supplies
                its own actions, e.g. the plan picks on billing). */}
            {(step.skippable || !step.hideContinue) && (
                <div className="shrink-0 flex items-center justify-between gap-2">
                    {step.skippable ? (
                        <LemonButton type="tertiary" size="small" onClick={skipStep}>
                            Skip for now
                        </LemonButton>
                    ) : (
                        <span />
                    )}
                    {!step.hideContinue && (
                        <LemonButton
                            type="primary"
                            status="alt"
                            sideIcon={<IconArrowRight />}
                            onClick={completeStep}
                            loading={isLast && isCompleting}
                        >
                            {isLast ? 'Finish' : isFirst ? 'Get started' : 'Continue'}
                        </LemonButton>
                    )}
                </div>
            )}
        </div>
    )
}
