import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { cn } from 'lib/utils/css-classes'

// Deliberate self-driving → legacy import: onboardingLogic owns the completion flow (marking the
// team onboarded, redirecting out) for both variants.
import { onboardingLogic } from '../legacy/onboardingLogic'
import { onboardingEventUsageLogic, type SelfDrivingOnboardingStepId } from '../onboardingEventUsageLogic'
import { BillingStep } from './steps/BillingStep'
import { InstallStep } from './steps/InstallStep'
import { WelcomeStep } from './steps/WelcomeStep'

/**
 * The self-driving onboarding: run the wizard, pick a plan, land in the inbox.
 *
 * The wizard's `self-driving` program does the actual configuration — GitHub, signal sources,
 * scouts — so this flow deliberately owns almost nothing. It shows the command, streams the run's
 * progress, and takes payment. Anything it asked for itself would be a second place to set the
 * same thing.
 */

interface StepDef {
    id: SelfDrivingOnboardingStepId
    title: string
    Content: (props: { onContinue: () => void; completing: boolean }) => JSX.Element
    skippable?: boolean
    /** Step provides its own primary action (e.g. plan picks), so suppress the footer Continue. */
    hideContinue?: boolean
    /** Tailwind `max-w-*` for the card on this step. Defaults to `max-w-xl`; wider steps (e.g. billing
     * with side-by-side plan cards) opt into more room. */
    maxWidth?: string
}

/**
 * Say what this is, run the wizard, pick a plan. The wizard does the real configuration (sources,
 * scouts, GitHub), so the app's job is to show the run and get out of the way — anything this flow
 * asked for separately would be a second place to set the same thing.
 */
const STEPS: StepDef[] = [
    { id: 'welcome', title: '', Content: WelcomeStep },
    { id: 'install', title: 'Install PostHog', Content: InstallStep },
    {
        id: 'billing',
        title: 'Pick a plan',
        Content: BillingStep,
        hideContinue: true,
        maxWidth: 'max-w-3xl',
    },
]

// The card: chrome (sm+ panel; full-bleed on mobile) plus the content flex-column. Width varies per
// step via StepDef.maxWidth — SelfDrivingOnboarding just provides the backdrop + logo.
const CARD_CLASSES =
    'relative w-full flex flex-col gap-5 overflow-hidden p-0 transition-[max-width] duration-300 sm:max-h-[calc(100dvh-7rem)] sm:p-8 md:p-10 sm:bg-surface-primary sm:rounded-xl sm:shadow-md sm:border sm:border-primary'

export function SelfDrivingOnboardingFlow(): JSX.Element {
    const { completeSelfDrivingOnboarding } = useActions(onboardingLogic)
    const { isCompleting } = useValues(onboardingLogic)
    const {
        reportSelfDrivingOnboardingStarted,
        reportSelfDrivingOnboardingStepViewed,
        reportSelfDrivingOnboardingStepCompleted,
        reportSelfDrivingOnboardingStepSkipped,
    } = useActions(onboardingEventUsageLogic)
    // Initialize from the URL so a refresh — or an OAuth callback that lands back on ?step=install
    // (e.g. the GitHub connect flow) — resumes where it left off instead of restarting at welcome.
    const [stepIndex, setStepIndex] = useState(() => {
        const fromUrl = STEPS.findIndex((s) => s.id === router.values.searchParams['step'])
        return fromUrl >= 0 ? fromUrl : 0
    })

    const step = STEPS[stepIndex]
    const isFirst = stepIndex === 0
    const isLast = stepIndex === STEPS.length - 1

    // Funnel (GROW-89): `started` fires once per fresh entry — a ?step= resume (refresh, OAuth
    // callback) is a continuation, not a new start. `step viewed` fires for every step shown,
    // including the one this mounts on.
    useOnMountEffect(() => {
        if (stepIndex === 0) {
            reportSelfDrivingOnboardingStarted()
        }
    })
    useEffect(() => {
        reportSelfDrivingOnboardingStepViewed(STEPS[stepIndex].id)
    }, [stepIndex, reportSelfDrivingOnboardingStepViewed])

    // Keep ?step= in sync as the user moves so the URL stays resumable, preserving any other params
    // (like the integration ids the GitHub callback appends).
    const goToStep = (index: number): void => {
        setStepIndex(index)
        router.actions.replace(router.values.location.pathname, {
            ...router.values.searchParams,
            step: STEPS[index].id,
        })
    }

    const advance = (): void => {
        if (isLast) {
            // Marks onboarding complete (credits the sources turned on) and navigates out, so
            // sceneLogic doesn't bounce the user back into onboarding.
            completeSelfDrivingOnboarding()
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
                        aria-label={`Step ${stepIndex + 1} of ${STEPS.length}`}
                    >
                        {STEPS.map((s, i) => (
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
                {step.title && <h1 className="text-2xl font-bold text-center m-0">{step.title}</h1>}
            </div>

            {/* Scrollable middle: fade edges + hover scrollbar so tall steps don't hard-crop. */}
            <ScrollableShadows direction="vertical" styledScrollbars className="flex-1 min-h-0" contentClassName="px-1">
                <step.Content onContinue={completeStep} completing={isLast && isCompleting} />
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
