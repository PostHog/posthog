import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { cn } from 'lib/utils/css-classes'

import selfDrivingHog from 'public/hedgehog/self-driving-hog.png'

// Deliberate self-driving → legacy import: onboardingLogic owns the completion flow (marking the
// team onboarded, redirecting out) for both variants.
import { onboardingLogic } from '../legacy/onboardingLogic'
import { type ContextOnboardingStepId, onboardingEventUsageLogic } from '../onboardingEventUsageLogic'
import { useWizardCommand } from '../shared/useWizardCommand'
import { SELF_DRIVING_WORKFLOW_ID } from '../shared/wizard-sync/installationProgressLogic'
import { InstallationProgressView, useLocalWizardRunActive } from '../shared/wizard-sync/InstallationProgressView'
import { WizardCommandBlock } from '../shared/wizard-sync/WizardCommandBlock'
import { WizardInstallOptions } from '../shared/wizard-sync/WizardInstallOptions'
import { ContextBillingStep } from './ContextBillingStep'

/**
 * The self-driving onboarding: run the wizard, pick a plan, land in the inbox.
 *
 * The wizard's `self-driving` program does the actual configuration — GitHub, signal sources,
 * scouts — so this flow deliberately owns almost nothing. It shows the command, streams the run's
 * progress, and takes payment. Anything it asked for itself would be a second place to set the
 * same thing.
 */

// ---- Steps ---------------------------------------------------------------------------------------

/** The opener: what self-driving is, before we ask anyone to paste a command. */
function WelcomeStep(): JSX.Element {
    return (
        <div className="flex flex-col items-center text-center gap-5">
            <img src={selfDrivingHog} alt="A hedgehog riding in a self-driving car" className="w-full rounded-lg" />
            <div className="flex flex-col gap-2">
                <h1 className="text-2xl font-bold m-0">Let's make your product self-driving</h1>
                <p className="text-muted max-w-md mx-auto m-0">
                    PostHog runs on your product's context. One command gets it flowing, then agents can start finding
                    and fixing things, with you steering.
                </p>
            </div>
        </div>
    )
}

/** What the self-driving run wires up, so the command isn't a leap of faith. */
const WIZARD_SETS_UP = [
    'Connects your GitHub, so agents can open pull requests',
    'Picks the signal sources and scouts worth watching',
    'Sends findings to your inbox as they land',
]

// The self-driving run is interactive: it asks about your issue tracker, walks you through the
// GitHub App install, and proposes scouts. The cloud runner can't do any of that (it runs headless
// and the CLI rejects `--ci` for this program), so the cloud arm is forced off here rather than
// being left to the experiment flag.
function InstallOptions({ onContinue }: { onContinue: () => void }): JSX.Element {
    const { isCloudOrDev } = useWizardCommand()
    const { reportContextOnboardingInstallModeSelected } = useActions(onboardingEventUsageLogic)

    // Self-hosted: the wizard CLI only targets cloud + dev, so the command block renders nothing.
    // Show a real, actionable fallback instead of an empty step.
    if (!isCloudOrDev) {
        return (
            <div className="flex flex-col gap-3">
                <p className="text-sm text-muted m-0">
                    Install the PostHog SDK for your framework and your product's context starts flowing in, ready for
                    agents to act on.
                </p>
                <LemonButton type="primary" to="https://posthog.com/docs/getting-started/install" targetBlank>
                    Read the install docs
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <p className="text-sm text-muted text-center m-0">
                Run this in your project. It sets everything up and hands back an inbox that's already working.
            </p>
            <WizardInstallOptions
                hideHog
                offerCloudRun={false}
                onQueued={onContinue}
                onModeSelected={reportContextOnboardingInstallModeSelected}
                localBlock={
                    <WizardCommandBlock
                        hideHog
                        subcommand="self-driving"
                        description="Takes about ten minutes. It'll ask you a few things along the way."
                    />
                }
            />
            <ul className="flex flex-col gap-1.5 m-0 p-0 list-none">
                {WIZARD_SETS_UP.map((line) => (
                    <li key={line} className="flex items-start gap-2">
                        <IconCheckCircle className="size-4 text-success shrink-0 mt-0.5" />
                        <span className="text-xs text-muted">{line}</span>
                    </li>
                ))}
            </ul>
        </div>
    )
}

/**
 * The step swaps to the live tracker as soon as the CLI registers a run. Sync is unconditional here
 * (no `ONBOARDING_WIZARD_SYNC` gate): without it this step is a static command with no feedback, and
 * watching the run is the whole point of the flow. There is no cloud run to coordinate with, so the
 * local session stream is the only source.
 */
function InstallStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    const isLocalRunActive = useLocalWizardRunActive(SELF_DRIVING_WORKFLOW_ID)
    return isLocalRunActive ? (
        <InstallationProgressView
            mode="local"
            workflowId={SELF_DRIVING_WORKFLOW_ID}
            continueHint="Keep answering the wizard in your terminal. Progress shows up here as it goes, so you can carry on with the rest of onboarding whenever you like."
        />
    ) : (
        <InstallOptions onContinue={onContinue} />
    )
}

// ---- Shell ---------------------------------------------------------------------------------------

interface StepDef {
    id: ContextOnboardingStepId
    title: string
    Content: (props: { onContinue: () => void }) => JSX.Element
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
        Content: ContextBillingStep,
        hideContinue: true,
        maxWidth: 'max-w-3xl',
    },
]

// The card: chrome (sm+ panel; full-bleed on mobile) plus the content flex-column. Width varies per
// step via StepDef.maxWidth — LegacyOnboarding just provides the backdrop + logo.
const CARD_CLASSES =
    'relative w-full flex flex-col gap-5 overflow-hidden p-0 transition-[max-width] duration-300 sm:max-h-[calc(100dvh-7rem)] sm:p-8 md:p-10 sm:bg-surface-primary sm:rounded-xl sm:shadow-md sm:border sm:border-primary'

export function ContextOnboarding(): JSX.Element {
    const { completeContextOnboarding } = useActions(onboardingLogic)
    const { isCompleting } = useValues(onboardingLogic)
    const {
        reportContextOnboardingStarted,
        reportContextOnboardingStepViewed,
        reportContextOnboardingStepCompleted,
        reportContextOnboardingStepSkipped,
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
            reportContextOnboardingStarted()
        }
    })
    useEffect(() => {
        reportContextOnboardingStepViewed(STEPS[stepIndex].id)
    }, [stepIndex, reportContextOnboardingStepViewed])

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
            completeContextOnboarding()
            return
        }
        goToStep(stepIndex + 1)
    }
    // Leaving a step forward is either completing it (Continue / the step's own primary action,
    // e.g. a queued cloud run or a plan pick) or skipping it — reported separately so the funnel
    // can tell drop-off from opt-out.
    const completeStep = (): void => {
        reportContextOnboardingStepCompleted(step.id)
        advance()
    }
    const skipStep = (): void => {
        reportContextOnboardingStepSkipped(step.id)
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
                    <div className="flex-1 flex items-center justify-center gap-1.5">
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
                <step.Content onContinue={completeStep} />
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
