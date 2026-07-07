import { useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'
import { type ReactNode, useEffect, useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconCheckCircle, IconGithub } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import type { TeamType } from '~/types'

import selfDrivingHog from 'public/hedgehog/self-driving-hog.png'

// Deliberate self-driving → legacy import: onboardingLogic owns the completion flow (marking the
// team onboarded, redirecting out) for both variants.
import { onboardingLogic } from '../legacy/onboardingLogic'
import { type ContextOnboardingStepId, onboardingEventUsageLogic } from '../onboardingEventUsageLogic'
import { useWizardCommand } from '../shared/SetupWizardBanner'
import { availableOnboardingProducts, getProductIcon, toSentenceCase } from '../shared/utils'
import { activeCloudRunLogic, type CloudRunHandle } from '../shared/wizard-sync/activeCloudRunLogic'
import { installationProgressLogic } from '../shared/wizard-sync/installationProgressLogic'
import { InstallationProgressView, useLocalWizardRunActive } from '../shared/wizard-sync/InstallationProgressView'
import { wizardCloudRunLogic } from '../shared/wizard-sync/wizardCloudRunLogic'
import { WizardCommandBlock } from '../shared/wizard-sync/WizardCommandBlock'
import { WizardInstallOptions } from '../shared/wizard-sync/WizardInstallOptions'
import { ContextBillingStep } from './ContextBillingStep'
import { ContextInviteStep } from './ContextInviteStep'
import { ContextWarehouseStep } from './ContextWarehouseStep'

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
            <img src={selfDrivingHog} alt="A hedgehog riding in a self-driving car" className="w-full rounded-lg" />
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

// One wizard, two ways to run it — the shared WizardInstallOptions owns the cloud/local switching
// and framework badges; this wraps it in the self-driving copy and manual-docs fallback.
function InstallOptions({ onContinue }: { onContinue: () => void }): JSX.Element {
    const cloudRunEnabled = useFeatureFlag('ONBOARDING_WIZARD_CLOUD_RUN', 'test')
    const { isCloudOrDev } = useWizardCommand()
    const { reportContextOnboardingInstallModeSelected } = useActions(onboardingEventUsageLogic)
    const offerCloud = cloudRunEnabled && isCloudOrDev

    // Self-hosted: the wizard CLI / cloud run only target cloud + dev, so both wizard blocks render
    // nothing. Show a real, actionable fallback instead of an empty step.
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
            {/* Establishes the priority order: the easy path (we run it, you get a PR) up front; the
                toggle below is the actor sub-choice; manual docs are the quiet fallback at the bottom. */}
            {offerCloud ? (
                <p className="text-sm text-muted text-center m-0">
                    Get your product's context flowing so agents can start finding and fixing things. The easiest way is
                    to let us set it up and open a PR you just review and merge.
                </p>
            ) : (
                <p className="text-sm text-muted text-center m-0">
                    Run the wizard to get your product's context flowing so agents can start finding and fixing things.
                </p>
            )}
            {/* GROW-96: kicking off the cloud run is the step's "next" action, so onQueued advances the flow. */}
            <WizardInstallOptions
                hideHog
                onQueued={onContinue}
                onModeSelected={reportContextOnboardingInstallModeSelected}
                localBlock={<WizardCommandBlock hideHog />}
            />
            <p className="text-xs text-muted m-0 text-center">
                Rather wire it up by hand?{' '}
                <Link to="https://posthog.com/docs/getting-started/install" target="_blank">
                    Read the install docs
                </Link>
            </p>
        </div>
    )
}

// When wizard sync is on and a LOCAL run is in flight, swap the options for the live tracker. A cloud
// run is already surfaced by the unified Installation layer (WizardCloudRunBlock → InstallationProgressView),
// and the cloud wizard posts to the same session — so suppress the local run view when a cloud run is
// active to avoid showing two progress components.
function InstallStepWithSync({ onContinue }: { onContinue: () => void }): JSX.Element {
    const isLocalRunActive = useLocalWizardRunActive()
    const { activeCloudRun } = useValues(activeCloudRunLogic)
    // The view claims the shared inline-panel flag itself, so no FAB coordination is needed here.
    const showLocalRun = isLocalRunActive && !activeCloudRun
    return showLocalRun ? <InstallationProgressView mode="local" /> : <InstallOptions onContinue={onContinue} />
}

function InstallStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    const isSyncEnabled = useFeatureFlag('ONBOARDING_WIZARD_SYNC', 'test')
    return isSyncEnabled ? <InstallStepWithSync onContinue={onContinue} /> : <InstallOptions onContinue={onContinue} />
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
    /** Spans both grid columns — for the card that carries extra config (web analytics domains). */
    wide?: boolean
}

// Tint a `rgb(r g b)` color string into a faint background fill for the icon chip.
function tint(color: string): string {
    return color.replace(/\)$/, ' / 0.12)')
}

// Card status reflects config, the SDK, and any in-flight install. The install delivers the SDK every
// source needs, so while it runs a turned-on source is "Installing" and a turned-off one reads
// "Available" — turn it on and it gets installed too. Otherwise it's "Active" once events arrive,
// "Needs install" if on with nothing running, or "Off".
function statusFor(
    active: boolean,
    sdkInstalled: boolean,
    installing: boolean
): { type: 'muted' | 'success' | 'warning' | 'primary'; label: string; loading?: boolean } {
    if (!active) {
        return installing ? { type: 'muted', label: 'Available' } : { type: 'muted', label: 'Off' }
    }
    if (installing) {
        return { type: 'primary', label: 'Installing', loading: true }
    }
    return sdkInstalled ? { type: 'success', label: 'Active' } : { type: 'warning', label: 'Needs install' }
}

function ToolCard({
    source,
    sdkInstalled,
    installing,
}: {
    source: ToolSource
    sdkInstalled: boolean
    installing: boolean
}): JSX.Element {
    const product = availableOnboardingProducts[source.productKey as keyof typeof availableOnboardingProducts]
    const color = product?.iconColor ?? 'var(--color-text-secondary)'
    const status = statusFor(source.active, sdkInstalled, installing)

    return (
        <div
            className={cn(
                'flex h-full flex-col gap-3 p-4 rounded-lg border transition-colors',
                source.active ? 'border-accent' : 'border-primary',
                source.wide && 'sm:col-span-2'
            )}
        >
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
                <LemonTag type={status.type} icon={status.loading ? <Spinner textColored /> : undefined}>
                    {status.label}
                </LemonTag>
            </div>
            <div className="flex flex-col gap-2">
                {source.toggles.map((toggle) => (
                    <div key={toggle.label} className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                            <p className={cn('m-0 text-sm', toggle.disabled && 'text-muted')}>{toggle.label}</p>
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
            {source.extra && <div>{source.extra}</div>}
        </div>
    )
}

interface CodebaseAccess {
    connected: boolean
    /** GitHub org/account the integration is connected to, shown in the connected state. */
    displayName: string | null
    /** OAuth URL to connect GitHub (activate codebase access) from here. */
    connectUrl: string
}

// Codebase access is a context source too — agents read the connected repo. Unlike the SDK-backed
// sources it doesn't ride the install; it's live as soon as GitHub is connected, so a user who skipped
// connecting during install can turn it on here.
function CodebaseAccessCard({ codebase }: { codebase: CodebaseAccess }): JSX.Element {
    return (
        <div
            className={cn(
                'flex h-full flex-col gap-3 p-4 rounded-lg border transition-colors',
                codebase.connected ? 'border-accent' : 'border-primary'
            )}
        >
            <div className="flex items-center gap-3">
                <div
                    className="size-9 rounded-md flex items-center justify-center shrink-0"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ backgroundColor: tint('rgb(100 116 139)') }}
                >
                    <IconGithub className="text-lg" />
                </div>
                <div className="flex-1 min-w-0">
                    <p className="m-0 text-sm font-semibold">Codebase access</p>
                    <p className="m-0 text-xs text-muted">Let agents read your code to find and fix issues.</p>
                </div>
                <LemonTag type={codebase.connected ? 'success' : 'muted'}>
                    {codebase.connected ? 'Active' : 'Off'}
                </LemonTag>
            </div>
            {codebase.connected ? (
                <div className="flex items-center gap-1.5 text-xs text-muted mt-auto">
                    <IconCheckCircle className="text-success" />
                    <span>Connected{codebase.displayName ? ` to ${codebase.displayName}` : ''}</span>
                </div>
            ) : (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconGithub />}
                    to={codebase.connectUrl}
                    disableClientSideRouting
                    className="self-start mt-auto"
                >
                    Connect GitHub
                </LemonButton>
            )}
        </div>
    )
}

function SourcesStep(): JSX.Element {
    const { activeCloudRun } = useValues(activeCloudRunLogic)
    // GitHub connection drives the codebase-access source, available whether or not a run is in flight.
    const { githubIntegration, connectGitHubUrl } = useValues(wizardCloudRunLogic)
    const codebase: CodebaseAccess = {
        connected: !!githubIntegration,
        displayName: githubIntegration?.display_name ?? null,
        connectUrl: connectGitHubUrl,
    }
    // Subscribe to the install stream only when a run exists — keeps this step from opening an SSE for
    // everyone who never triggered one.
    return activeCloudRun ? (
        <SourcesStepWithRun run={activeCloudRun} codebase={codebase} />
    ) : (
        <SourcesStepInner installing={false} repository={null} codebase={codebase} />
    )
}

// While a cloud run is connecting/running, the sources it would feed aren't live yet. Pass that down
// along with the repo it's landing in, so the step can name the install target once.
function SourcesStepWithRun({ run, codebase }: { run: CloudRunHandle; codebase: CodebaseAccess }): JSX.Element {
    const { installationProgress } = useValues(
        installationProgressLogic({ mode: 'cloud', runId: run.runId, taskId: run.taskId })
    )
    const { selectedRepository } = useValues(wizardCloudRunLogic)
    const installing = installationProgress.phase === 'connecting' || installationProgress.phase === 'running'
    return (
        <SourcesStepInner
            installing={installing}
            repository={installing ? selectedRepository : null}
            codebase={codebase}
        />
    )
}

// Exported for Storybook: the presentational sources step takes `installing`, the install's repo, and the
// codebase-access state as props, so stories can render every state without standing up the live logics.
export function SourcesStepInner({
    installing,
    repository,
    codebase,
}: {
    installing: boolean
    repository: string | null
    codebase: CodebaseAccess
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useAsyncActions(teamLogic)
    const { reportContextOnboardingSourceToggled } = useActions(onboardingEventUsageLogic)

    const autocaptureOn = !currentTeam?.autocapture_opt_out
    const replayOn = !!currentTeam?.session_recording_opt_in
    // Web analytics scopes to the team's authorized domains (app_urls); without one it has nothing to track.
    const hasAuthorizedDomain = (currentTeam?.app_urls?.length ?? 0) > 0
    // Every source here collects through the posthog-js SDK; ingested_event is our proxy for it being
    // installed and sending. Until then, turned-on sources read as "Needs install".
    const sdkInstalled = !!currentTeam?.ingested_event

    // Report to the v2 funnel (GROW-89) only after the PATCH lands: on failure the switch snaps back
    // to the team's real state, so a funnel event would record a toggle that never happened.
    // `toggle` names the switch — a card can carry several.
    const toggleSource = (productKey: ProductKey, toggle: string, enabled: boolean, patch: Partial<TeamType>): void => {
        void updateCurrentTeam(patch)
            .then(() => reportContextOnboardingSourceToggled(productKey, toggle, enabled))
            .catch(() => {}) // a failed write is not a toggle; the UI already reflects the revert
    }

    const sources: ToolSource[] = [
        {
            productKey: ProductKey.PRODUCT_ANALYTICS,
            active: autocaptureOn,
            toggles: [
                {
                    label: 'Autocapture events',
                    description: 'Clicks, pageviews, and inputs captured automatically.',
                    checked: autocaptureOn,
                    onChange: (checked) =>
                        toggleSource(ProductKey.PRODUCT_ANALYTICS, 'autocapture', checked, {
                            autocapture_opt_out: !checked,
                        }),
                },
                {
                    label: 'Heatmaps',
                    description: 'Aggregate clicks, scrolls, and mouse movement.',
                    checked: !!currentTeam?.heatmaps_opt_in,
                    onChange: (checked) =>
                        toggleSource(ProductKey.PRODUCT_ANALYTICS, 'heatmaps', checked, { heatmaps_opt_in: checked }),
                },
            ],
        },
        {
            productKey: ProductKey.SESSION_REPLAY,
            active: replayOn,
            toggles: [
                {
                    label: 'Record sessions',
                    checked: replayOn,
                    onChange: (checked) =>
                        toggleSource(ProductKey.SESSION_REPLAY, 'session_recording', checked, {
                            session_recording_opt_in: checked,
                        }),
                },
                {
                    label: 'Console logs',
                    checked: !!currentTeam?.capture_console_log_opt_in,
                    onChange: (checked) =>
                        toggleSource(ProductKey.SESSION_REPLAY, 'console_logs', checked, {
                            capture_console_log_opt_in: checked,
                        }),
                    disabled: !replayOn,
                },
                {
                    label: 'Network performance',
                    checked: !!currentTeam?.capture_performance_opt_in,
                    onChange: (checked) =>
                        toggleSource(ProductKey.SESSION_REPLAY, 'network_performance', checked, {
                            capture_performance_opt_in: checked,
                        }),
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
                    onChange: (checked) =>
                        toggleSource(ProductKey.ERROR_TRACKING, 'exception_autocapture', checked, {
                            autocapture_exceptions_opt_in: checked,
                        }),
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
                    onChange: (checked) =>
                        toggleSource(ProductKey.WEB_ANALYTICS, 'web_vitals', checked, {
                            autocapture_web_vitals_opt_in: checked,
                        }),
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
    ]

    return (
        <div className="flex flex-col gap-4">
            <p className="text-sm text-muted m-0">
                {!installing ? (
                    "Active sources feed context to PostHog. Turn on what's relevant — you can change these any time."
                ) : repository ? (
                    <>
                        Installing PostHog into <span className="font-mono text-default">{repository}</span>. Turn on
                        anything you want included.
                    </>
                ) : (
                    'Installing PostHog. Turn on anything you want included.'
                )}
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <CodebaseAccessCard codebase={codebase} />
                {sources.map((source) => (
                    <ToolCard
                        key={source.productKey}
                        source={source}
                        sdkInstalled={sdkInstalled}
                        installing={installing}
                    />
                ))}
            </div>
        </div>
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

const STEPS: StepDef[] = [
    { id: 'welcome', title: '', Content: WelcomeStep },
    { id: 'install', title: 'Install PostHog', Content: InstallStep },
    { id: 'sources', title: 'Turn on your sources', Content: SourcesStep, skippable: true, maxWidth: 'max-w-3xl' },
    { id: 'warehouse', title: 'Connect your data', Content: ContextWarehouseStep, skippable: true },
    {
        id: 'billing',
        title: 'Pick a plan',
        Content: ContextBillingStep,
        hideContinue: true,
        maxWidth: 'max-w-3xl',
    },
    { id: 'invite', title: 'Invite your team', Content: ContextInviteStep, skippable: true },
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
