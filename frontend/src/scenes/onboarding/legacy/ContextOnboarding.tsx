import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { type ReactNode, useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconPullRequest, IconTerminal } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import selfDrivingHog from 'public/hedgehog/self-driving-hog.png'

import { ContextBillingStep } from './ContextBillingStep'
import { ContextInviteStep } from './ContextInviteStep'
import { ContextWarehouseStep } from './ContextWarehouseStep'
import { onboardingLogic } from './onboardingLogic'
import { WizardCloudRunBlock } from './sdks/OnboardingInstallStep/WizardCloudRunBlock'
import { WizardCommandBlock } from './sdks/OnboardingInstallStep/WizardCommandBlock'
import { WizardFrameworkBadges } from './sdks/OnboardingInstallStep/WizardModeShell'
import { useWizardTakeoverActive, WizardProgressTracker } from './sdks/OnboardingInstallStep/WizardProgressTracker'
import { useWizardCommand } from '../shared/SetupWizardBanner'
import { availableOnboardingProducts, getProductIcon, toSentenceCase } from '../shared/utils'

/**
 * Context-first onboarding (prototype, legacy variant). A fixed linear flow, one thing per step,
 * that replaces "pick a use case → pick products". Steps configure the context PostHog runs on.
 * Real where cheap (install command, source toggles → team props); warehouse/billing/invite and
 * completion wiring are still thin and marked for follow-up.
 */

// ---- Steps ---------------------------------------------------------------------------------------

function WelcomeStep(): JSX.Element {
    return (
        <div className="flex flex-col items-center text-center gap-5">
            <img
                src={selfDrivingHog}
                alt="A hedgehog riding in a self-driving car"
                className="w-full rounded-lg"
            />
            <div className="flex flex-col gap-2">
                <h1 className="text-2xl font-bold m-0">Let's make your product self-driving</h1>
                <p className="text-muted max-w-md mx-auto m-0">
                    PostHog runs on your product's context. We'll get it flowing in a few steps, then agents can start
                    finding and fixing things, with you steering.
                </p>
            </div>
        </div>
    )
}

type InstallMode = 'cloud' | 'local'

// One wizard, two ways to run it: have us run it and open a PR (the self-driving path), or run the
// CLI yourself. A segmented control switches between them. The cloud path only exists behind
// ONBOARDING_WIZARD_CLOUD_RUN on cloud/dev; elsewhere this collapses to just the local command.
// hideHog keeps the compact onboarding card free of the wizard hedgehog.
function InstallOptions(): JSX.Element {
    const cloudRunEnabled = useFeatureFlag('ONBOARDING_WIZARD_CLOUD_RUN', 'test')
    const { isCloudOrDev } = useWizardCommand()
    const [mode, setMode] = useState<InstallMode>('cloud')
    const offerCloud = cloudRunEnabled && isCloudOrDev

    // Self-hosted: the wizard CLI / cloud run only target cloud + dev, so both wizard blocks render
    // nothing. Show a real, actionable fallback instead of an empty step.
    if (!isCloudOrDev) {
        return (
            <div className="flex flex-col gap-3">
                <p className="text-sm text-muted m-0">
                    Install the PostHog SDK for your framework, then events start flowing here automatically.
                </p>
                <LemonButton type="primary" to="https://posthog.com/docs/getting-started/install" targetBlank>
                    Installation docs
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            {/* Frameworks are the same whichever way the wizard runs, so the badges sit above the selector. */}
            {isCloudOrDev && <WizardFrameworkBadges />}
            {offerCloud && (
                <LemonSegmentedButton
                    fullWidth
                    value={mode}
                    onChange={(value) => setMode(value)}
                    options={[
                        {
                            value: 'cloud',
                            label: 'Open a pull request',
                            icon: <IconPullRequest />,
                            'data-attr': 'context-wizard-mode-cloud',
                        },
                        {
                            value: 'local',
                            label: 'Run it yourself',
                            icon: <IconTerminal />,
                            'data-attr': 'context-wizard-mode-local',
                        },
                    ]}
                />
            )}
            {/* No onQueued: unlike the legacy install step, this flow's footer Continue is always
                enabled (install is non-blocking), so a queued cloud run needs no extra unblock signal. */}
            {offerCloud && mode === 'cloud' ? <WizardCloudRunBlock hideHog /> : <WizardCommandBlock hideHog />}
            <p className="text-xs text-muted m-0 text-center">
                Prefer to do it by hand?{' '}
                <Link to="https://posthog.com/docs/getting-started/install" target="_blank">
                    Manual install docs
                </Link>
            </p>
        </div>
    )
}

// When wizard sync is on and a local run is in flight, swap the options for the live tracker. Mounting
// it sets `panelMounted`, which hides the global WizardProgressFab (AuthenticatedShell) while we're on
// this step; once the user moves to a later step, the FAB carries the same progress headlessly.
function InstallStepWithSync(): JSX.Element {
    const isTakeoverActive = useWizardTakeoverActive()
    return isTakeoverActive ? <WizardProgressTracker /> : <InstallOptions />
}

function InstallStep(): JSX.Element {
    const isSyncEnabled = useFeatureFlag('ONBOARDING_WIZARD_SYNC', 'test')
    return isSyncEnabled ? <InstallStepWithSync /> : <InstallOptions />
}

interface ToolToggle {
    label: string
    description?: string
    checked: boolean
    onChange: (checked: boolean) => void
    disabled?: boolean
}

interface ToolSource {
    productKey: ProductKey
    /** Whether this tool is configured to produce meaningful context. */
    active: boolean
    /** Shown under the tool name when context comes from something other than the toggles below. */
    note?: string
    toggles: ToolToggle[]
    /** Extra config rendered under the toggles (e.g. web analytics authorized domains). */
    extra?: ReactNode
}

// Tint a `rgb(r g b)` color string into a faint background fill for the icon chip.
function tint(color: string): string {
    return color.replace(/\)$/, ' / 0.12)')
}

function ToolCard({ source }: { source: ToolSource }): JSX.Element {
    const product = availableOnboardingProducts[source.productKey as keyof typeof availableOnboardingProducts]
    const color = product?.iconColor ?? 'var(--color-text-secondary)'

    return (
        <div className="flex flex-col gap-3 p-4 border border-primary rounded-lg">
            <div className="flex items-center gap-3">
                <div
                    className="size-9 rounded-md flex items-center justify-center shrink-0"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ backgroundColor: tint(color) }}
                >
                    {getProductIcon(product?.icon, { iconColor: color, className: 'text-lg' })}
                </div>
                <div className="flex-1 min-w-0">
                    <p className="m-0 text-sm font-semibold">{toSentenceCase(product?.name ?? source.productKey)}</p>
                    {source.note && <p className="m-0 text-xs text-muted">{source.note}</p>}
                </div>
                <LemonTag type={source.active ? 'success' : 'muted'}>{source.active ? 'Active' : 'Off'}</LemonTag>
            </div>
            <div className="flex flex-col gap-2 pl-12">
                {source.toggles.map((toggle) => (
                    <div key={toggle.label} className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                            <p className={`m-0 text-sm ${toggle.disabled ? 'text-muted' : ''}`}>{toggle.label}</p>
                            {toggle.description && <p className="m-0 text-xs text-muted">{toggle.description}</p>}
                        </div>
                        <LemonSwitch
                            checked={toggle.checked}
                            onChange={toggle.onChange}
                            disabled={toggle.disabled}
                            size="small"
                        />
                    </div>
                ))}
            </div>
            {source.extra && <div className="pl-12">{source.extra}</div>}
        </div>
    )
}

function SourcesStep(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const autocaptureOn = !currentTeam?.autocapture_opt_out
    const replayOn = !!currentTeam?.session_recording_opt_in
    // Web analytics scopes to the team's authorized domains (app_urls); without one it has nothing to track.
    const hasAuthorizedDomain = (currentTeam?.app_urls?.length ?? 0) > 0

    const sources: ToolSource[] = [
        {
            productKey: ProductKey.PRODUCT_ANALYTICS,
            active: autocaptureOn,
            toggles: [
                {
                    label: 'Autocapture events',
                    description: 'Clicks, pageviews, and inputs captured automatically.',
                    checked: autocaptureOn,
                    onChange: (checked) => updateCurrentTeam({ autocapture_opt_out: !checked }),
                },
                {
                    label: 'Heatmaps',
                    description: 'Aggregate clicks, scrolls, and mouse movement.',
                    checked: !!currentTeam?.heatmaps_opt_in,
                    onChange: (checked) => updateCurrentTeam({ heatmaps_opt_in: checked }),
                },
            ],
        },
        {
            productKey: ProductKey.WEB_ANALYTICS,
            active: autocaptureOn && hasAuthorizedDomain,
            toggles: [
                {
                    label: 'Web vitals',
                    description: 'Load times and layout shifts from real users.',
                    checked: !!currentTeam?.autocapture_web_vitals_opt_in,
                    onChange: (checked) => updateCurrentTeam({ autocapture_web_vitals_opt_in: checked }),
                },
            ],
            extra: (
                <div className="flex flex-col gap-1.5">
                    <p className="m-0 text-sm">Authorized domains</p>
                    <p className="m-0 text-xs text-muted">Add the domains you want web analytics to track.</p>
                    <AuthorizedUrlList
                        type={AuthorizedUrlListType.WEB_ANALYTICS}
                        allowWildCards={false}
                        showLaunch={false}
                        displaySuggestions={false}
                        hideEmptyState
                        addText="Add a domain"
                    />
                </div>
            ),
        },
        {
            productKey: ProductKey.SESSION_REPLAY,
            active: replayOn,
            toggles: [
                {
                    label: 'Record sessions',
                    checked: replayOn,
                    onChange: (checked) => updateCurrentTeam({ session_recording_opt_in: checked }),
                },
                {
                    label: 'Console logs',
                    checked: !!currentTeam?.capture_console_log_opt_in,
                    onChange: (checked) => updateCurrentTeam({ capture_console_log_opt_in: checked }),
                    disabled: !replayOn,
                },
                {
                    label: 'Network performance',
                    checked: !!currentTeam?.capture_performance_opt_in,
                    onChange: (checked) => updateCurrentTeam({ capture_performance_opt_in: checked }),
                    disabled: !replayOn,
                },
            ],
        },
        {
            productKey: ProductKey.ERROR_TRACKING,
            active: !!currentTeam?.autocapture_exceptions_opt_in,
            toggles: [
                {
                    label: 'Capture exceptions',
                    description: 'Errors and stack traces as they happen.',
                    checked: !!currentTeam?.autocapture_exceptions_opt_in,
                    onChange: (checked) => updateCurrentTeam({ autocapture_exceptions_opt_in: checked }),
                },
            ],
        },
        {
            productKey: ProductKey.SURVEYS,
            active: !!currentTeam?.surveys_opt_in,
            toggles: [
                {
                    label: 'Enable surveys',
                    description: 'Collect feedback from inside your product.',
                    checked: !!currentTeam?.surveys_opt_in,
                    onChange: (checked) => updateCurrentTeam({ surveys_opt_in: checked }),
                },
            ],
        },
    ]

    return (
        <div className="flex flex-col gap-3">
            <p className="text-sm text-muted m-0">
                Active sources feed context to PostHog. Turn on what's relevant. You can change these any time.
            </p>
            {sources.map((source) => (
                <ToolCard key={source.productKey} source={source} />
            ))}
        </div>
    )
}

// ---- Shell ---------------------------------------------------------------------------------------

interface StepDef {
    id: string
    title: string
    Content: (props: { onContinue: () => void }) => JSX.Element
    skippable?: boolean
    /** Step provides its own primary action (e.g. plan picks), so suppress the footer Continue. */
    hideContinue?: boolean
}

const STEPS: StepDef[] = [
    { id: 'welcome', title: '', Content: WelcomeStep },
    { id: 'install', title: 'Install PostHog', Content: InstallStep },
    { id: 'sources', title: 'Turn on your sources', Content: SourcesStep, skippable: true },
    { id: 'warehouse', title: 'Connect your data', Content: ContextWarehouseStep, skippable: true },
    { id: 'billing', title: 'Pick a plan', Content: ContextBillingStep, skippable: true, hideContinue: true },
    { id: 'invite', title: 'Invite your team', Content: ContextInviteStep, skippable: true },
]

export function ContextOnboarding(): JSX.Element {
    const { completeContextOnboarding } = useActions(onboardingLogic)
    const { isCompleting } = useValues(onboardingLogic)
    // Initialize from the URL so a refresh — or an OAuth callback that lands back on ?step=install
    // (e.g. the GitHub connect flow) — resumes where it left off instead of restarting at welcome.
    const [stepIndex, setStepIndex] = useState(() => {
        const fromUrl = STEPS.findIndex((s) => s.id === router.values.searchParams['step'])
        return fromUrl >= 0 ? fromUrl : 0
    })

    const step = STEPS[stepIndex]
    const isFirst = stepIndex === 0
    const isLast = stepIndex === STEPS.length - 1

    // Keep ?step= in sync as the user moves so the URL stays resumable, preserving any other params
    // (like the integration ids the GitHub callback appends).
    const goToStep = (index: number): void => {
        setStepIndex(index)
        router.actions.replace(router.values.location.pathname, {
            ...router.values.searchParams,
            step: STEPS[index].id,
        })
    }

    const goNext = (): void => {
        if (isLast) {
            // Marks onboarding complete (credits the sources turned on) and navigates out, so
            // sceneLogic doesn't bounce the user back into onboarding.
            completeContextOnboarding()
            return
        }
        goToStep(stepIndex + 1)
    }
    const goBack = (): void => goToStep(Math.max(0, stepIndex - 1))

    return (
        // flex-1 + min-h-0 lets this fill the capped card (sm+) so the middle can scroll; on mobile the
        // card isn't height-bounded, so it just flows.
        <div className="flex flex-col gap-5 flex-1 min-h-0">
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
                <step.Content onContinue={goNext} />
            </ScrollableShadows>

            {/* Pinned footer */}
            <div className="shrink-0 flex items-center justify-between gap-2">
                {step.skippable ? (
                    <LemonButton type="tertiary" size="small" onClick={goNext}>
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
                        onClick={goNext}
                        loading={isLast && isCompleting}
                    >
                        {isLast ? 'Finish' : isFirst ? 'Get started' : 'Continue'}
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
