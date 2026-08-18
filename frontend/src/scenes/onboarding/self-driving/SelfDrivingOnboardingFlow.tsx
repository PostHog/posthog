import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { RealtimeCheckIndicator } from '../legacy/sdks/RealtimeCheckIndicator'
import {
    onboardingEventUsageLogic,
    SELF_DRIVING_ONBOARDING_EVENT_PROPS,
    type SelfDrivingOnboardingStepId,
} from '../onboardingEventUsageLogic'
import { resolveSetup } from '../shared/useCases'
import type { OnboardingExtraStepId, OnboardingUseCaseKey } from '../shared/useCases'
import { wizardSyncUiLogic } from '../shared/wizard-sync/wizardSyncUiLogic'
import { InstallationTrackerGate } from './components/InstallationTracker'
import { ManualSetupButton } from './components/SelfDrivingInstallOptions'
import { onboardingLogic } from './onboardingLogic'
import { RoughMark } from './RoughMark'
import { AIObservabilityStep } from './steps/AIObservabilityStep'
import { AuthorizedUrlsStep } from './steps/AuthorizedUrlsStep'
import { BillingStep } from './steps/BillingStep'
import { InstallStep } from './steps/InstallStep'
import { ToolsStep } from './steps/ToolsStep'
import { UseCasesStep } from './steps/UseCasesStep'
import { WelcomeStep } from './steps/WelcomeStep'
import { useCaseSelectionLogic } from './useCaseSelectionLogic'

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

// The steps a use case can declare as `extraSteps` - only ones that need the user's own input.
const EXTRA_STEPS: Record<OnboardingExtraStepId, StepDef> = {
    'authorized-urls': {
        id: 'authorized-urls',
        title: 'Add your website URLs',
        Content: AuthorizedUrlsStep,
        hideContinue: true,
    },
    'ai-observability': {
        id: 'ai-observability',
        title: 'Instrument your AI app',
        Content: AIObservabilityStep,
        hideContinue: true,
        maxWidth: 'max-w-2xl',
    },
}

function buildSteps(useCase: OnboardingUseCaseKey | null): StepDef[] {
    return [
        { id: 'welcome', title: '', Content: WelcomeStep },
        // The step id stays 'goals' so existing funnel queries continue to work.
        {
            id: 'goals',
            title: 'What do you want to get done first?',
            Content: UseCasesStep,
            hideContinue: true,
            maxWidth: 'max-w-2xl',
        },
        // The use case's tool collection is shown before install so the user knows what they are getting.
        {
            id: 'tools',
            title: 'Your tools',
            Content: ToolsStep,
            hideContinue: true,
            maxWidth: 'max-w-2xl',
        },
        { id: 'install', title: 'Install PostHog', Content: InstallStep },
        // The declared use case FILTERS what comes after install: only steps it can't reach its
        // finish line without. These steps render their own action zone, so the footer Continue is
        // suppressed.
        ...(resolveSetup(useCase).extraSteps ?? []).map((id) => EXTRA_STEPS[id]),
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
    'relative w-full flex flex-col gap-5 overflow-hidden p-0 sm:max-h-[calc(100dvh-7rem)] sm:p-8 md:p-10 sm:bg-surface-primary sm:rounded-2xl sm:shadow-[0_16px_40px_rgb(30_50_10_/_25%)] sm:border sm:border-primary'

export function SelfDrivingOnboardingFlow(): JSX.Element {
    const { claimInlinePanel, releaseInlinePanel } = useActions(wizardSyncUiLogic)
    // The flow surfaces the run itself (install-step tracker, header pill), so claim the inline
    // panel for its whole lifetime - the corner FAB never appears during onboarding.
    useEffect(() => {
        claimInlinePanel('local')
        return () => releaseInlinePanel('local')
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])
    const { completeOnboarding } = useActions(onboardingLogic)
    const { isCompleting } = useValues(onboardingLogic)
    const { reportOnboardingStarted, reportOnboardingStepCompleted, reportOnboardingStepSkipped } =
        useActions(eventUsageLogic)
    const { reportOnboardingStepViewed, reportOnboardingInstallVerified } = useActions(onboardingEventUsageLogic)
    // The step list depends on the declared use case (persisted, so a refresh keeps the
    // conditional steps in place).
    const { selectedUseCase } = useValues(useCaseSelectionLogic)
    const steps = useMemo(() => buildSteps(selectedUseCase), [selectedUseCase])
    // Track the current step by id, not index, so use-case changes (which insert/remove steps)
    // can't shift the user onto a different step. Initialize from the URL so a refresh — or an OAuth
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
            reportOnboardingStarted('welcome', SELF_DRIVING_ONBOARDING_EVENT_PROPS)
        }
    })
    useEffect(() => {
        reportOnboardingStepViewed(step.id)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [step.id, reportOnboardingStepViewed])

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
            // Marks onboarding complete (credits the sources turned on, plus the declared use
            // case's product) and navigates out, so sceneLogic doesn't bounce the user back in.
            completeOnboarding(selectedUseCase)
            return
        }
        goToStep(stepIndex + 1)
    }
    // Leaving a step forward is either completing it (Continue / the step's own primary action,
    // e.g. a queued cloud run or a plan pick) or skipping it — reported separately so the funnel
    // can tell drop-off from opt-out.
    const completeStep = (): void => {
        reportOnboardingStepCompleted(step.id, undefined, SELF_DRIVING_ONBOARDING_EVENT_PROPS)
        advance()
    }
    const skipStep = (): void => {
        reportOnboardingStepSkipped(step.id, undefined, SELF_DRIVING_ONBOARDING_EVENT_PROPS)
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
                {/* The dots are absolutely centered so uneven side content (back button vs the
                    verification chip or run pill) can never shift them off the card's midline. */}
                <div className="relative flex items-center justify-between gap-2 w-full min-h-8">
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
                        className="absolute left-1/2 -translate-x-1/2 flex items-center gap-1.5"
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
                    <div className="min-w-0 flex justify-end">
                        {/* On the install step, live verification: flips when the team's first event
                            lands, whichever install path produced it. Past the install step, the run
                            keeps a quiet presence up here; on the install step itself the tracker
                            lives in the content. */}
                        {step.id === 'install' && (
                            <RealtimeCheckIndicator
                                teamPropertyToVerify="ingested_event"
                                minimal
                                onComplete={reportOnboardingInstallVerified}
                            />
                        )}
                        {stepIndex > steps.findIndex((s) => s.id === 'install') && <InstallationTrackerGate />}
                    </div>
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
                        <div className="flex items-center gap-2">
                            {step.id === 'install' && <ManualSetupButton />}
                            <LemonButton
                                type="primary"
                                status="alt"
                                sideIcon={<IconArrowRight />}
                                onClick={completeStep}
                                loading={isLast && isCompleting}
                            >
                                {isLast ? 'Finish' : isFirst ? 'Get started' : 'Continue'}
                            </LemonButton>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
