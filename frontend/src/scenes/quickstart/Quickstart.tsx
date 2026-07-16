import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'

import {
    IconApps,
    IconArrowLeft,
    IconArrowRight,
    IconBook,
    IconBuilding,
    IconCheckCircle,
    IconChevronDown,
    IconFolder,
    IconGear,
    IconGraduationCap,
    IconLogomark,
    IconPeople,
    IconReceipt,
    IconSparkles,
    IconTerminal,
} from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSkeleton, LemonTag, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { liveUserCountLogic } from 'lib/components/LiveUserCount'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyCurrency, humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { billingLogic } from 'scenes/billing/billingLogic'
import {
    AIObservabilitySDKInstructions,
    AIObservabilitySDKTagOverrides,
} from 'scenes/onboarding/legacy/sdks/ai-observability/AIObservabilitySDKInstructions'
import { ErrorTrackingSDKInstructions } from 'scenes/onboarding/legacy/sdks/error-tracking/ErrorTrackingSDKInstructions'
import { ExperimentsSDKInstructions } from 'scenes/onboarding/legacy/sdks/experiments/ExperimentsSDKInstructions'
import { FeatureFlagsSDKInstructions } from 'scenes/onboarding/legacy/sdks/feature-flags/FeatureFlagsSDKInstructions'
import { useAdblockDetection } from 'scenes/onboarding/legacy/sdks/hooks/useAdblockDetection'
import { useInstallationComplete } from 'scenes/onboarding/legacy/sdks/hooks/useInstallationComplete'
import { LogsSDKInstructions } from 'scenes/onboarding/legacy/sdks/logs/LogsSDKInstructions'
import { SDKGrid } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep/SDKGrid'
import { ProductAnalyticsSDKInstructions } from 'scenes/onboarding/legacy/sdks/product-analytics/ProductAnalyticsSDKInstructions'
import { AdblockWarning } from 'scenes/onboarding/legacy/sdks/RealtimeCheckIndicator'
import { sdksLogic } from 'scenes/onboarding/legacy/sdks/sdksLogic'
import { SDKSnippet } from 'scenes/onboarding/legacy/sdks/SDKSnippet'
import { SessionReplaySDKInstructions } from 'scenes/onboarding/legacy/sdks/session-replay/SessionReplaySDKInstructions'
import { SurveysSDKInstructions } from 'scenes/onboarding/legacy/sdks/surveys/SurveysSDKInstructions'
import { WebAnalyticsSDKInstructions } from 'scenes/onboarding/legacy/sdks/web-analytics/WebAnalyticsSDKInstructions'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'
import { getProductIcon } from 'scenes/onboarding/shared/utils'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'
import {
    BillingProductV2Type,
    OnboardingStepKey,
    SDK,
    SDKInstructionsMap,
    SDKKey,
    SDKTagOverrides,
    SidePanelTab,
} from '~/types'

import {
    PublicationFeedKey,
    QUICKSTART_BLOG_URL,
    QUICKSTART_NEWSLETTER_URL,
    QuickstartPublication,
} from './publications'
import { QuickstartJourneyStep, QuickstartProduct, QuickstartToolStatus, quickstartLogic } from './quickstartLogic'

export const scene: SceneExport = {
    component: Quickstart,
    logic: quickstartLogic,
}

function captureQuickstartAction(action: string, productKey?: string, properties?: Record<string, string>): void {
    posthog.capture('quickstart action clicked', {
        action,
        ...(productKey ? { product_key: productKey } : {}),
        ...properties,
    })
}

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }): JSX.Element {
    return (
        <div className="mb-4">
            <h2 className="text-lg font-semibold mb-0">{title}</h2>
            {subtitle && <p className="text-secondary mb-0 mt-1">{subtitle}</p>}
        </div>
    )
}

function WaitingForEventsIndicator(): JSX.Element {
    return (
        <div className="flex items-center gap-2 px-2 py-1 border border-accent rounded-sm self-start">
            <div className="relative flex items-center justify-center">
                <div className="absolute w-3 h-3 border-2 border-accent rounded-full animate-ping" />
                <div className="w-2 h-2 bg-accent rounded-full" />
            </div>
            <span className="text-sm text-accent whitespace-nowrap">Waiting for your first event…</span>
        </div>
    )
}

function LiveUsersRightNow(): JSX.Element | null {
    const logicProps = { pollIntervalMs: 30000 }
    const { liveUserCount } = useValues(liveUserCountLogic(logicProps))
    const { pauseStream, resumeStream } = useActions(liveUserCountLogic(logicProps))
    const { isVisible } = usePageVisibility()

    useEffect(() => {
        if (isVisible) {
            resumeStream()
        } else {
            pauseStream()
        }
    }, [isVisible, resumeStream, pauseStream])

    return (
        <Link
            to={urls.webAnalyticsLive()}
            onClick={() => captureQuickstartAction('view_live_users')}
            className="flex items-center gap-1.5 text-xs text-tertiary hover:text-primary"
            data-attr="quickstart-live-users"
        >
            <span className="relative flex items-center justify-center shrink-0">
                <span className="absolute w-3 h-3 bg-success rounded-full animate-ping opacity-75" />
                <span className="relative w-2 h-2 bg-success rounded-full" />
            </span>
            <span>
                {liveUserCount === null
                    ? 'Live users'
                    : `${humanFriendlyLargeNumber(liveUserCount)} live ${liveUserCount === 1 ? 'user' : 'users'}`}
            </span>
        </Link>
    )
}

function ProjectToken({ inline = false }: { inline?: boolean }): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

    if (!currentTeam?.api_token) {
        return null
    }

    // Once data is flowing the token is reference material, not a setup step, so it
    // collapses to a quiet single line
    if (inline) {
        return (
            <div
                className="flex items-center gap-1.5 text-xs text-tertiary min-w-0"
                onClick={() => captureQuickstartAction('copy_project_token')}
                data-attr="quickstart-copy-project-token"
            >
                <span className="whitespace-nowrap">Project token</span>
                <CopyToClipboardInline
                    explicitValue={currentTeam.api_token}
                    description="project token"
                    iconSize="xsmall"
                    className="font-mono min-w-0"
                >
                    {currentTeam.api_token}
                </CopyToClipboardInline>
            </div>
        )
    }

    return (
        <div
            className="flex flex-col gap-1 w-fit max-w-full min-w-0"
            onClick={() => captureQuickstartAction('copy_project_token')}
            data-attr="quickstart-copy-project-token"
        >
            <LemonLabel info="Every SDK snippet uses it. Write-only, so it's safe in public apps.">
                Project token
            </LemonLabel>
            <CodeSnippet compact wrap thing="project token">
                {currentTeam.api_token}
            </CodeSnippet>
        </div>
    )
}

function UsageThisPeriod(): JSX.Element | null {
    const { isCloudOrDev } = useValues(preflightLogic)
    const { billing, canAccessBilling } = useValues(billingLogic)

    if (!isCloudOrDev || !canAccessBilling || !billing) {
        return null
    }

    const interval = billing.billing_period?.interval === 'year' ? 'year' : 'month'
    const eventsUsage = billing.products?.find(
        (product: BillingProductV2Type) => product.type === ProductKey.PRODUCT_ANALYTICS
    )?.current_usage

    let label: string | null = null
    if (billing.has_active_subscription && billing.current_total_amount_usd !== undefined) {
        label = `${humanFriendlyCurrency(billing.current_total_amount_usd)} this ${interval}`
    } else if (eventsUsage !== undefined) {
        // Free plans have no spend to show, but usage against the free tier is still meaningful
        label = `${humanFriendlyLargeNumber(eventsUsage)} events this ${interval}`
    }
    if (!label) {
        return null
    }

    return (
        <Link
            to={urls.organizationBilling()}
            onClick={() => captureQuickstartAction('view_billing_usage')}
            className="flex items-center gap-1 text-xs text-tertiary hover:text-primary"
            data-attr="quickstart-billing-usage"
        >
            <IconReceipt />
            <span>{label}</span>
        </Link>
    )
}

/** Workspace chrome: where you are, what it costs, what's happening right now */
function WorkspaceStrip(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-tertiary">
            <div className="flex flex-wrap items-center gap-x-1.5 min-w-0">
                {currentOrganization?.name ? (
                    <span className="flex items-center gap-1">
                        <IconBuilding />
                        {currentOrganization.name}
                    </span>
                ) : null}
                {currentOrganization?.name && currentTeam?.name ? <span>/</span> : null}
                {currentTeam?.name ? (
                    <span className="flex items-center gap-1">
                        <IconFolder />
                        {currentTeam.name}
                    </span>
                ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-x-3">
                <UsageThisPeriod />
                <LiveUsersRightNow />
            </div>
        </div>
    )
}

function HeaderStat({ icon, children }: { icon: JSX.Element; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center gap-1.5 text-sm text-secondary">
            <span className="text-base leading-none">{icon}</span>
            {children}
        </div>
    )
}

function InstallHeroCard(): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const { showInviteModal } = useActions(inviteLogic)

    return (
        <LemonCard hoverEffect={false} className="rounded-lg border-transparent shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-2 mb-4">
                <SectionHeader
                    title="Get your data flowing"
                    subtitle="PostHog needs events from your app. One install powers every tool below."
                />
                <WaitingForEventsIndicator />
            </div>
            <div className="grid grid-cols-1 @3xl/main-content:grid-cols-2 gap-6">
                {isCloudOrDev && (
                    <div className="flex flex-col gap-2">
                        <h3 className="text-sm font-semibold mb-0">Fastest: the AI setup wizard</h3>
                        <p className="text-secondary text-sm mb-0">
                            Run this in your project root. It detects your framework, installs the SDK, and configures
                            event capture for you.
                        </p>
                        <CodeSnippet language={Language.Bash}>{wizardCommand}</CodeSnippet>
                    </div>
                )}
                <div className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold mb-0">Other ways to get set up</h3>
                    <LemonButton
                        type="secondary"
                        fullWidth
                        to={urls.onboarding({
                            productKey: ProductKey.PRODUCT_ANALYTICS,
                            stepKey: OnboardingStepKey.INSTALL,
                        })}
                        onClick={() => captureQuickstartAction('install_manually')}
                        data-attr="quickstart-install-manually"
                    >
                        Follow the install guide for your framework
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        fullWidth
                        onClick={() => {
                            captureQuickstartAction('invite_teammate')
                            showInviteModal()
                        }}
                        data-attr="quickstart-invite-teammate"
                    >
                        Invite a developer to install it for you
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        fullWidth
                        to={urls.sources()}
                        onClick={() => captureQuickstartAction('connect_source')}
                        data-attr="quickstart-connect-source"
                    >
                        No app? Connect a data source instead
                    </LemonButton>
                </div>
            </div>
            {/* Installing is the token's moment: every manual guide asks for it */}
            <div className="mt-6">
                <ProjectToken />
            </div>
        </LemonCard>
    )
}

function SubsectionHeader({ title }: { title: string }): JSX.Element {
    return <h3 className="text-sm font-semibold mb-3">{title}</h3>
}

function ProductStatusTag({ level }: { level: QuickstartToolStatus['level'] }): JSX.Element {
    if (level === 'live') {
        return (
            <Tooltip title="Real data came in during the last 30 days" delayMs={0}>
                <LemonTag type="success">Live</LemonTag>
            </Tooltip>
        )
    }
    if (level === 'ready') {
        return (
            <Tooltip title="Set up and waiting for its first data" delayMs={0}>
                <LemonTag type="highlight">Ready</LemonTag>
            </Tooltip>
        )
    }
    return (
        <Tooltip title="Needs an install or configuration before it can collect data" delayMs={0}>
            <LemonTag type="muted">Needs setup</LemonTag>
        </Tooltip>
    )
}

function JourneyOverlay({
    journey,
    productKey,
}: {
    journey: QuickstartJourneyStep[]
    productKey: ProductKey
}): JSX.Element {
    const { openTaskGuidance } = useActions(quickstartLogic)
    const sections = [
        { title: 'Get it live', steps: journey.filter((step) => step.kind === 'activation') },
        { title: 'Improve quality', steps: journey.filter((step) => step.kind === 'quality') },
    ].filter((section) => section.steps.length > 0)

    return (
        <div className="p-2 max-w-100 flex flex-col gap-3">
            {sections.map((section) => (
                <div key={section.title}>
                    <div className="text-xs font-semibold text-secondary mb-1">{section.title}</div>
                    <ul className="flex flex-col gap-1 mb-0">
                        {section.steps.map((step) => (
                            <li key={step.key}>
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    fullWidth
                                    center={false}
                                    icon={
                                        step.achieved ? (
                                            <IconCheckCircle className="text-success" />
                                        ) : (
                                            <span className="w-3 h-3 rounded-full border-2 border-current text-muted-alt" />
                                        )
                                    }
                                    sideIcon={<IconArrowRight />}
                                    onClick={() => {
                                        captureQuickstartAction('open_tool_task', productKey, { step_key: step.key })
                                        openTaskGuidance(productKey, step.key)
                                    }}
                                    data-attr={`quickstart-task-${productKey}-${step.key}`}
                                >
                                    <span
                                        className={`whitespace-normal text-left ${step.achieved ? 'text-tertiary' : ''}`}
                                    >
                                        {step.label}
                                    </span>
                                </LemonButton>
                            </li>
                        ))}
                    </ul>
                </div>
            ))}
        </div>
    )
}

function JourneyMeter({ status, productKey }: { status: QuickstartToolStatus; productKey: ProductKey }): JSX.Element {
    return (
        <LemonDropdown
            overlay={<JourneyOverlay journey={status.journey} productKey={productKey} />}
            placement="bottom-end"
            onVisibilityChange={(visible) => visible && captureQuickstartAction('view_tool_journey', productKey)}
        >
            <button
                type="button"
                className="flex items-center gap-2 w-full p-0 border-0 bg-transparent cursor-pointer group"
                aria-label="Show setup details"
                data-attr={`quickstart-journey-${productKey}`}
            >
                <span className="flex items-center gap-1 flex-1">
                    {status.journey.map((step) => (
                        <span
                            key={step.key}
                            className={`h-1 flex-1 rounded-full transition-colors ${
                                step.achieved
                                    ? 'bg-success'
                                    : step.key === status.nextStep?.key
                                      ? 'bg-accent'
                                      : 'bg-fill-tertiary'
                            }`}
                        />
                    ))}
                </span>
                <span className="text-xs text-tertiary group-hover:text-primary">Setup details</span>
                <IconChevronDown className="text-tertiary group-hover:text-primary" />
            </button>
        </LemonDropdown>
    )
}

function getToolActivitySummary(status: QuickstartToolStatus): JSX.Element {
    if (status.stat) {
        return (
            <>
                <span className="font-semibold">{humanFriendlyLargeNumber(status.stat.value)}</span>{' '}
                <span className="text-secondary">{status.stat.label}</span>
            </>
        )
    }
    if (status.level === 'live') {
        return <span className="text-secondary">Active in the last 30 days</span>
    }
    if (status.level === 'ready') {
        return <span className="text-secondary">Waiting for its first signal</span>
    }
    return <span className="text-secondary">Not collecting data yet</span>
}

/** Activity evidence and the best available improvement, without implying a finite completion goal. */
function ToolStatusPanel({
    status,
    productKey,
}: {
    status: QuickstartToolStatus
    productKey: ProductKey
}): JSX.Element {
    const { openTaskGuidance } = useActions(quickstartLogic)
    const nextStep = status.nextStep

    return (
        <div className="flex flex-col gap-2 border-t pt-3">
            <div className="text-sm min-w-0 truncate min-h-5">{getToolActivitySummary(status)}</div>
            <JourneyMeter status={status} productKey={productKey} />
            <div className="min-h-16 text-xs">
                {nextStep ? (
                    <>
                        <div className="font-medium text-secondary mb-0.5">Next improvement</div>
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            fullWidth
                            center={false}
                            sideIcon={<IconArrowRight />}
                            onClick={() => {
                                captureQuickstartAction('open_recommended_task', productKey, {
                                    step_key: nextStep.key,
                                })
                                openTaskGuidance(productKey, nextStep.key)
                            }}
                            data-attr={`quickstart-recommended-task-${productKey}`}
                        >
                            <span className="whitespace-normal text-left font-medium text-accent line-clamp-2">
                                {nextStep.label}
                            </span>
                        </LemonButton>
                    </>
                ) : (
                    <>
                        <div className="font-medium text-secondary">Setup quality</div>
                        <div className="font-medium">No suggested changes right now</div>
                    </>
                )}
            </div>
        </div>
    )
}

export function ProductCard({ product }: { product: QuickstartProduct }): JSX.Element {
    const { enablingProducts } = useValues(quickstartLogic)
    const { enableProduct, openToolSetupModal } = useActions(quickstartLogic)
    const { status } = product

    const setUpButton = (
        <LemonButton
            type="primary"
            size="small"
            to={PRODUCT_SDK_SETUP[product.key] ? undefined : product.setupUrl}
            onClick={() => {
                captureQuickstartAction('set_up_product', product.key)
                if (PRODUCT_SDK_SETUP[product.key]) {
                    openToolSetupModal(product.key)
                }
            }}
            data-attr={`quickstart-setup-${product.key}`}
        >
            {status.cta === 'install' ? 'Install' : 'Set up'}
        </LemonButton>
    )
    const enableButton = (type: 'primary' | 'secondary'): JSX.Element => (
        <LemonButton
            type={type}
            size="small"
            loading={!!enablingProducts[product.key]}
            onClick={() => enableProduct(product.key)}
            data-attr={`quickstart-enable-${product.key}`}
        >
            Enable
        </LemonButton>
    )
    const openButton = (
        <LemonButton
            type="primary"
            size="small"
            to={product.url}
            onClick={() => captureQuickstartAction('open_product', product.key)}
            data-attr={`quickstart-open-${product.key}`}
        >
            Open
        </LemonButton>
    )

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-4 rounded-lg border-transparent shadow-sm">
            <div className="flex items-start justify-between gap-2">
                <span className="text-2xl leading-none">
                    {getProductIcon(product.icon, { iconColor: product.iconColor })}
                </span>
                <ProductStatusTag level={status.level} />
            </div>
            <div>
                <h3 className="font-semibold text-base mb-0">{product.name}</h3>
                <div className="text-xs text-tertiary">Best for {product.bestFor}</div>
            </div>
            <p className="text-secondary text-sm mb-0 flex-1">{product.description}</p>
            <ToolStatusPanel status={status} productKey={product.key} />
            <div className="flex items-center gap-2 mt-1">
                {status.level === 'live' ? (
                    <>
                        {openButton}
                        {/* e.g. error tracking live from a server SDK can still turn on web autocapture */}
                        {status.cta === 'enable' && enableButton('secondary')}
                    </>
                ) : status.cta === 'enable' ? (
                    enableButton('primary')
                ) : status.cta === 'open' ? (
                    <>
                        {openButton}
                        {PRODUCT_SDK_SETUP[product.key] && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    captureQuickstartAction('open_sdk_guide', product.key)
                                    openToolSetupModal(product.key)
                                }}
                                data-attr={`quickstart-sdk-guide-${product.key}`}
                            >
                                SDK guide
                            </LemonButton>
                        )}
                    </>
                ) : (
                    setUpButton
                )}
                {product.docsUrl && (
                    <LemonButton
                        size="small"
                        to={product.docsUrl}
                        targetBlank
                        onClick={() => captureQuickstartAction('open_docs', product.key)}
                        data-attr={`quickstart-docs-${product.key}`}
                    >
                        Docs
                    </LemonButton>
                )}
            </div>
        </LemonCard>
    )
}

const PRODUCT_SDK_SETUP: Partial<
    Record<ProductKey, { instructionsMap: SDKInstructionsMap; tagOverrides?: SDKTagOverrides; verifyingName?: string }>
> = {
    [ProductKey.PRODUCT_ANALYTICS]: { instructionsMap: ProductAnalyticsSDKInstructions },
    [ProductKey.WEB_ANALYTICS]: { instructionsMap: WebAnalyticsSDKInstructions },
    [ProductKey.SESSION_REPLAY]: { instructionsMap: SessionReplaySDKInstructions },
    [ProductKey.ERROR_TRACKING]: { instructionsMap: ErrorTrackingSDKInstructions },
    [ProductKey.SURVEYS]: { instructionsMap: SurveysSDKInstructions },
    [ProductKey.FEATURE_FLAGS]: { instructionsMap: FeatureFlagsSDKInstructions },
    [ProductKey.EXPERIMENTS]: { instructionsMap: ExperimentsSDKInstructions },
    [ProductKey.AI_OBSERVABILITY]: {
        instructionsMap: AIObservabilitySDKInstructions,
        tagOverrides: AIObservabilitySDKTagOverrides,
        verifyingName: 'LLM generation',
    },
    [ProductKey.LOGS]: { instructionsMap: LogsSDKInstructions },
}

function ToolSetupModalContent({
    product,
    installationComplete,
}: {
    product: QuickstartProduct
    installationComplete: boolean
}): JSX.Element {
    const setup = PRODUCT_SDK_SETUP[product.key]
    const { filteredSDKs, selectedSDK, tags, searchTerm, selectedTag } = useValues(sdksLogic)
    const {
        setAvailableSDKInstructionsMap,
        setSDKTagOverrides,
        selectSDK,
        setSelectedSDK,
        setSearchTerm,
        setSelectedTag,
    } = useActions(sdksLogic)
    const { currentTeam } = useValues(teamLogic)
    const adblockResult = useAdblockDetection()

    useEffect(() => {
        setSDKTagOverrides(setup?.tagOverrides ?? {})
        setAvailableSDKInstructionsMap(setup?.instructionsMap ?? {})
        setSelectedSDK(null)
    }, [setup, setAvailableSDKInstructionsMap, setSDKTagOverrides, setSelectedSDK])

    if (!setup) {
        return <p className="text-secondary mb-0">Follow the setup guide to get {product.name} running.</p>
    }

    if (!selectedSDK) {
        return (
            <SDKGrid
                filteredSDKs={filteredSDKs ?? []}
                searchTerm={searchTerm}
                selectedTag={selectedTag}
                tags={tags}
                onSDKClick={(sdk: SDK) => selectSDK(sdk)}
                onSearchChange={setSearchTerm}
                onTagChange={setSelectedTag}
                currentTeam={currentTeam}
                showTopControls
                installationComplete={installationComplete}
                showTopSkipButton={false}
            />
        )
    }

    const instructions = setup.instructionsMap[selectedSDK.key as SDKKey] as (() => JSX.Element) | undefined

    return (
        <div className="flex flex-col gap-3">
            <div>
                <LemonButton
                    icon={<IconArrowLeft />}
                    size="xsmall"
                    onClick={() => setSelectedSDK(null)}
                    data-attr="quickstart-sdk-back"
                >
                    All SDKs
                </LemonButton>
            </div>
            {instructions ? (
                <SDKSnippet sdk={selectedSDK} sdkInstructions={instructions} />
            ) : (
                <p className="text-secondary mb-0">Instructions for this SDK live in the full setup guide.</p>
            )}
            <AdblockWarning adblockResult={adblockResult} />
        </div>
    )
}

function ToolSetupModal({ installationComplete }: { installationComplete: boolean }): JSX.Element {
    const { setupModalProduct } = useValues(quickstartLogic)
    const { closeToolSetupModal } = useActions(quickstartLogic)

    return (
        <LemonModal
            isOpen={!!setupModalProduct}
            onClose={closeToolSetupModal}
            title={setupModalProduct ? `Set up ${setupModalProduct.name}` : ''}
            width="52rem"
            footer={
                setupModalProduct && (
                    <div className="flex items-center justify-end gap-2">
                        {setupModalProduct.docsUrl && (
                            <LemonButton
                                to={setupModalProduct.docsUrl}
                                targetBlank
                                onClick={() => captureQuickstartAction('open_docs', setupModalProduct.key)}
                                data-attr="quickstart-setup-modal-docs"
                            >
                                Docs
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            to={setupModalProduct.setupUrl}
                            onClick={() => {
                                captureQuickstartAction('open_setup_guide', setupModalProduct.key)
                                closeToolSetupModal()
                            }}
                            data-attr="quickstart-setup-modal-guide"
                        >
                            Open full setup guide
                        </LemonButton>
                    </div>
                )
            }
        >
            {setupModalProduct && (
                <ToolSetupModalContent product={setupModalProduct} installationComplete={installationComplete} />
            )}
        </LemonModal>
    )
}

function TaskGuidanceModal(): JSX.Element {
    const { selectedTask, enablingProducts } = useValues(quickstartLogic)
    const { closeTaskGuidance, enableProduct, openToolSetupModal } = useActions(quickstartLogic)

    const primaryAction = (): JSX.Element | null => {
        if (!selectedTask) {
            return null
        }

        const { product, step } = selectedTask
        const captureAction = (): void => {
            captureQuickstartAction('start_tool_task', product.key, {
                step_key: step.key,
                task_action: step.guide.action,
            })
        }

        if (step.guide.action === 'enable') {
            return (
                <LemonButton
                    type="primary"
                    loading={!!enablingProducts[product.key]}
                    disabledReason={step.achieved ? 'This is already enabled' : undefined}
                    onClick={() => {
                        captureAction()
                        enableProduct(product.key)
                    }}
                    data-attr="quickstart-task-enable"
                >
                    {step.achieved ? 'Enabled' : step.guide.actionLabel}
                </LemonButton>
            )
        }

        if (step.guide.action === 'setup' && PRODUCT_SDK_SETUP[product.key]) {
            return (
                <LemonButton
                    type="primary"
                    onClick={() => {
                        captureAction()
                        closeTaskGuidance()
                        openToolSetupModal(product.key)
                    }}
                    data-attr="quickstart-task-setup"
                >
                    {step.guide.actionLabel}
                </LemonButton>
            )
        }

        const destination =
            step.guide.action === 'docs'
                ? (step.guide.url ?? product.docsUrl ?? product.setupUrl)
                : step.guide.action === 'open_product'
                  ? product.url
                  : product.setupUrl

        return (
            <LemonButton
                type="primary"
                to={destination}
                targetBlank={step.guide.action === 'docs'}
                onClick={() => {
                    captureAction()
                    closeTaskGuidance()
                }}
                data-attr="quickstart-task-open"
            >
                {step.guide.actionLabel}
            </LemonButton>
        )
    }

    return (
        <LemonModal
            isOpen={!!selectedTask}
            onClose={closeTaskGuidance}
            title={selectedTask?.step.label ?? ''}
            width="32rem"
            footer={
                selectedTask && (
                    <div className="flex items-center justify-end gap-2">
                        <LemonButton onClick={closeTaskGuidance}>Close</LemonButton>
                        {primaryAction()}
                    </div>
                )
            }
        >
            {selectedTask && (
                <div className="flex flex-col gap-4">
                    <div className="flex items-center gap-2">
                        <span className="text-xl leading-none">
                            {getProductIcon(selectedTask.product.icon, { iconColor: selectedTask.product.iconColor })}
                        </span>
                        <span className="font-medium">{selectedTask.product.name}</span>
                        {selectedTask.step.achieved && <LemonTag type="success">Done</LemonTag>}
                    </div>
                    <p className="text-secondary mb-0">{selectedTask.step.guide.description}</p>
                    <div>
                        <div className="font-semibold mb-2">How to do it</div>
                        <ol className="flex flex-col gap-2 list-decimal pl-5 mb-0">
                            {selectedTask.step.guide.instructions.map((instruction) => (
                                <li key={instruction} className="pl-1">
                                    {instruction}
                                </li>
                            ))}
                        </ol>
                    </div>
                </div>
            )}
        </LemonModal>
    )
}

interface LearnQuickLink {
    label: string
    icon: JSX.Element
    to?: string
    targetBlank?: boolean
    onClick?: () => void
}

function LearnCard({
    icon,
    title,
    description,
    buttonLabel,
    to,
    targetBlank,
    onClick,
    action,
    quickLinks,
}: {
    icon: JSX.Element
    title: string
    description: string
    buttonLabel: string
    to?: string
    targetBlank?: boolean
    onClick?: () => void
    action: string
    quickLinks?: LearnQuickLink[]
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-4 rounded-lg border-transparent shadow-sm">
            <span className="text-xl text-secondary">{icon}</span>
            <h3 className="font-semibold text-base mb-0">{title}</h3>
            <p className="text-secondary text-sm mb-0">{description}</p>
            {quickLinks ? (
                <>
                    <ul className="flex flex-col gap-1.5 my-1 flex-1">
                        {quickLinks.map((link) => (
                            <li key={link.label} className="flex">
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    fullWidth
                                    center={false}
                                    icon={link.icon}
                                    to={link.to}
                                    targetBlank={link.targetBlank}
                                    onClick={() => {
                                        captureQuickstartAction(`${action}_quick_link`, undefined, {
                                            link_label: link.label,
                                        })
                                        link.onClick?.()
                                    }}
                                    data-attr={`quickstart-learn-${action}-quick-link`}
                                >
                                    <span className="whitespace-normal text-left font-normal">{link.label}</span>
                                </LemonButton>
                            </li>
                        ))}
                    </ul>
                    <div className="mt-auto flex">
                        <Link
                            to={to}
                            target={targetBlank ? '_blank' : undefined}
                            targetBlankIcon={targetBlank}
                            onClick={() => {
                                captureQuickstartAction(action)
                                onClick?.()
                            }}
                            className="text-sm font-medium inline-flex items-center gap-1"
                            data-attr={`quickstart-learn-${action}`}
                        >
                            {buttonLabel}
                            {!targetBlank && <IconArrowRight />}
                        </Link>
                    </div>
                </>
            ) : (
                <div className="mt-auto flex">
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={to}
                        targetBlank={targetBlank}
                        onClick={() => {
                            captureQuickstartAction(action)
                            onClick?.()
                        }}
                        data-attr={`quickstart-learn-${action}`}
                    >
                        {buttonLabel}
                    </LemonButton>
                </div>
            )}
        </LemonCard>
    )
}

function PublicationCard({
    publication,
    feed,
}: {
    publication: QuickstartPublication
    feed: PublicationFeedKey
}): JSX.Element {
    return (
        <LemonCard hoverEffect className="p-0 overflow-hidden h-full rounded-lg border-transparent shadow-sm">
            <Link
                to={publication.url}
                target="_blank"
                className="flex flex-col h-full text-primary hover:text-primary"
                onClick={() =>
                    posthog.capture('quickstart action clicked', {
                        action: 'open_publication',
                        feed,
                        url: publication.url,
                    })
                }
                data-attr={`quickstart-publication-card-${feed}`}
            >
                {publication.imageUrl && (
                    <img
                        src={publication.imageUrl}
                        alt=""
                        className="w-full aspect-video object-cover bg-surface-secondary"
                        loading="lazy"
                        onError={(e) => {
                            e.currentTarget.style.display = 'none'
                        }}
                    />
                )}
                <div className="flex flex-col gap-1 p-3 flex-1">
                    <h3 className="font-semibold text-sm mb-0 line-clamp-2">{publication.title}</h3>
                    <p className="text-secondary text-xs mb-0 line-clamp-2 flex-1">{publication.description}</p>
                    <div className="text-xs text-tertiary mt-1">
                        {[
                            publication.author,
                            dayjs(publication.publishedAt).isValid() ? dayjs(publication.publishedAt).fromNow() : null,
                        ]
                            .filter(Boolean)
                            .join(' · ')}
                    </div>
                </div>
            </Link>
        </LemonCard>
    )
}

function LoadMoreSentinel({ onVisible }: { onVisible: () => void }): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        const element = ref.current
        if (!element) {
            return
        }
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) {
                    onVisible()
                }
            },
            { rootMargin: '400px' }
        )
        observer.observe(element)
        return () => observer.disconnect()
    }, [onVisible])

    return <div ref={ref} className="h-px" />
}

function PublicationSkeletonCard(): JSX.Element {
    return (
        <LemonCard
            hoverEffect={false}
            className="flex flex-col gap-2 p-3 h-full rounded-lg border-transparent shadow-sm"
        >
            <LemonSkeleton className="w-full h-24 rounded" />
            <LemonSkeleton className="w-3/4 h-4" />
            <LemonSkeleton className="w-full h-3" />
        </LemonCard>
    )
}

function PublicationRail({
    feed,
    title,
    viewAllUrl,
    viewAllLabel,
    endLabel,
    publications,
    loading,
    hasMore,
    onLoadMore,
}: {
    feed: PublicationFeedKey
    title: string
    viewAllUrl: string
    viewAllLabel: string
    endLabel: string
    publications: QuickstartPublication[]
    loading: boolean
    hasMore: boolean
    onLoadMore: () => void
}): JSX.Element | null {
    if (!loading && publications.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold mb-0">{title}</h3>
                <Link
                    to={viewAllUrl}
                    target="_blank"
                    className="text-sm"
                    onClick={() => captureQuickstartAction(`view_all_${feed}`)}
                    data-attr={`quickstart-publications-view-all-${feed}`}
                >
                    {viewAllLabel}
                </Link>
            </div>
            <ScrollableShadows
                direction="horizontal"
                innerClassName="snap-x"
                contentClassName="flex w-max min-w-full items-stretch gap-4 pb-1"
                styledScrollbars
            >
                {publications.map((publication) => (
                    <div key={publication.url} className="w-72 shrink-0 snap-start">
                        <PublicationCard publication={publication} feed={feed} />
                    </div>
                ))}
                {loading &&
                    Array.from({ length: publications.length === 0 ? 4 : 2 }, (_, index) => (
                        <div key={`skeleton-${index}`} className="w-72 shrink-0">
                            <PublicationSkeletonCard />
                        </div>
                    ))}
                {!loading && hasMore && <LoadMoreSentinel onVisible={onLoadMore} />}
                {!loading && !hasMore && publications.length > 0 && (
                    <div className="w-56 shrink-0 snap-start flex items-center justify-center rounded border border-dashed p-4 text-center">
                        <Link
                            to={viewAllUrl}
                            target="_blank"
                            className="text-sm"
                            onClick={() => captureQuickstartAction(`view_all_${feed}`)}
                            data-attr={`quickstart-publications-feed-end-${feed}`}
                        >
                            {endLabel}
                        </Link>
                    </div>
                )}
            </ScrollableShadows>
        </div>
    )
}

function PublicationsSection(): JSX.Element | null {
    const {
        blogPublications,
        blogPublicationsLoading,
        newsletterPublications,
        newsletterPublicationsLoading,
        publicationsHasMore,
    } = useValues(quickstartLogic)
    const { loadMoreBlogPublications, loadMoreNewsletterPublications } = useActions(quickstartLogic)

    const nothingToShow =
        !blogPublicationsLoading &&
        blogPublications.length === 0 &&
        !newsletterPublicationsLoading &&
        newsletterPublications.length === 0
    if (nothingToShow) {
        return null
    }

    return (
        <div className="flex flex-col gap-6">
            <PublicationRail
                feed="blog"
                title="From the blog"
                viewAllUrl={QUICKSTART_BLOG_URL}
                viewAllLabel="View all posts"
                endLabel="Keep reading on the blog"
                publications={blogPublications}
                loading={blogPublicationsLoading}
                hasMore={publicationsHasMore.blog}
                onLoadMore={loadMoreBlogPublications}
            />
            <PublicationRail
                feed="newsletter"
                title="build mode, our newsletter"
                viewAllUrl={QUICKSTART_NEWSLETTER_URL}
                viewAllLabel="Read & subscribe"
                endLabel="More issues + subscribe"
                publications={newsletterPublications}
                loading={newsletterPublicationsLoading}
                hasMore={publicationsHasMore.newsletter}
                onLoadMore={loadMoreNewsletterPublications}
            />
        </div>
    )
}

export function Quickstart(): JSX.Element {
    const { products, activeProductCount, totalProductCount } = useValues(quickstartLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { showConfigureHomeModal } = useActions(navigationLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const installationComplete = useInstallationComplete('ingested_event')

    const quickstartVariant = featureFlags[FEATURE_FLAGS.QUICKSTART_HOMEPAGE]
    useEffect(() => {
        // The route can outlive enrollment (it's persisted as some users' homepage),
        // so a non-test variant gets sent home instead of stranded on a dead page
        if (quickstartVariant !== undefined && quickstartVariant !== 'test') {
            router.actions.replace(urls.projectHomepage())
        }
    }, [quickstartVariant])

    if (quickstartVariant !== 'test') {
        // Flags still loading, or the redirect above is about to land
        return <SpinnerOverlay sceneLevel />
    }

    return (
        // Capped and centered like onboarding's product selection: full-width reads stretched
        // and empty on large monitors, a ~72rem column keeps the page dense
        <SceneContent className="gap-y-8 py-4 w-full max-w-6xl mx-auto">
            {/* Workspace chrome hugs the hero: tighter within the zone than between zones */}
            <div className="flex flex-col gap-4">
                <WorkspaceStrip />
                {/* Standard scene header: title left, actions right. This page is a recurring
                    homepage, so it gets utility, not a one-time welcome ceremony. */}
                <section>
                    <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-2">
                        <div className="min-w-0">
                            <h1 className="text-2xl font-bold mb-1">Quickstart</h1>
                            <p className="text-secondary mb-0 max-w-140">
                                Every tool here runs on the same events. Get data flowing once, then turn things on as
                                you need them.
                            </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonButton
                                type="primary"
                                size="small"
                                icon={<IconSparkles />}
                                onClick={() => {
                                    captureQuickstartAction('ask_posthog_ai_header')
                                    openSidePanel(SidePanelTab.Max)
                                }}
                                data-attr="quickstart-header-ask-posthog-ai"
                            >
                                Ask PostHog AI
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPeople />}
                                onClick={() => {
                                    captureQuickstartAction('invite_teammate_header')
                                    showInviteModal()
                                }}
                                data-attr="quickstart-header-invite"
                            >
                                Invite teammates
                            </LemonButton>
                            <LemonButton
                                size="small"
                                icon={<IconGear />}
                                tooltip="Choose what your Home button opens"
                                onClick={() => {
                                    captureQuickstartAction('configure_homepage')
                                    showConfigureHomeModal()
                                }}
                                data-attr="quickstart-header-configure-home"
                            >
                                Change homepage
                            </LemonButton>
                        </div>
                    </div>
                    {installationComplete && (
                        <div className="mt-3">
                            <ProjectToken inline />
                        </div>
                    )}
                </section>
            </div>

            {!installationComplete && <InstallHeroCard />}

            <section>
                <div className="flex flex-wrap items-start justify-between gap-x-8">
                    <SectionHeader
                        title="Turn on your tools"
                        subtitle="What most teams start with. Active tools are collecting data. Ready tools are set up and waiting for their first signal."
                    />
                    <HeaderStat icon={<IconApps />}>
                        {activeProductCount} of {totalProductCount} live
                    </HeaderStat>
                </div>
                <div className="grid grid-cols-1 @2xl/main-content:grid-cols-2 @5xl/main-content:grid-cols-3 gap-4">
                    {products.map((product) => (
                        <ProductCard key={product.key} product={product} />
                    ))}
                </div>
            </section>

            <section>
                <SectionHeader title="Go further" subtitle="Guides, companion apps, and what's new from PostHog." />
                <div className="flex flex-col gap-6">
                    <div>
                        <SubsectionHeader title="Learn the ropes" />
                        <div className="grid grid-cols-1 @3xl/main-content:grid-cols-3 gap-4">
                            <LearnCard
                                icon={<IconSparkles className="text-ai" />}
                                title="Ask PostHog AI anything"
                                description="Once events are flowing, ask questions in plain English and get answers from your live data. Try one:"
                                buttonLabel="Ask PostHog AI"
                                onClick={() => openSidePanel(SidePanelTab.Max)}
                                action="ask_posthog_ai"
                                quickLinks={[
                                    'What are my most visited pages this week?',
                                    'How many daily active users this week?',
                                    'Where do users drop off in my app?',
                                ].map((question) => ({
                                    label: question,
                                    icon: <IconSparkles className="text-ai" />,
                                    // The ! prefix makes the side panel submit the question right away
                                    onClick: () => openSidePanel(SidePanelTab.Max, `!${question}`),
                                }))}
                            />
                            <LearnCard
                                icon={<IconBook />}
                                title="Read the docs"
                                description="Guides for every tool, SDK, and framework, from first install to advanced setups. Start here:"
                                buttonLabel="Browse all docs"
                                to="https://posthog.com/docs"
                                targetBlank
                                action="open_docs_home"
                                quickLinks={[
                                    {
                                        label: 'Capture custom events',
                                        icon: <IconBook />,
                                        to: 'https://posthog.com/docs/product-analytics/capture-events',
                                        targetBlank: true,
                                    },
                                    {
                                        label: 'Identify your users',
                                        icon: <IconBook />,
                                        to: 'https://posthog.com/docs/product-analytics/identify',
                                        targetBlank: true,
                                    },
                                    {
                                        label: 'Define actions from events',
                                        icon: <IconBook />,
                                        to: 'https://posthog.com/docs/data/actions',
                                        targetBlank: true,
                                    },
                                ]}
                            />
                            <LearnCard
                                icon={<IconGraduationCap />}
                                title="Follow a tutorial"
                                description="Step-by-step walkthroughs of real setups: funnels, feature flags, A/B tests, and more. Popular picks:"
                                buttonLabel="Browse all tutorials"
                                to="https://posthog.com/tutorials"
                                targetBlank
                                action="open_tutorials"
                                quickLinks={[
                                    {
                                        label: 'Complete guide to event tracking',
                                        icon: <IconGraduationCap />,
                                        to: 'https://posthog.com/tutorials/event-tracking-guide',
                                        targetBlank: true,
                                    },
                                    {
                                        label: 'Understand behavior with session replays',
                                        icon: <IconGraduationCap />,
                                        to: 'https://posthog.com/tutorials/explore-insights-session-recordings',
                                        targetBlank: true,
                                    },
                                    {
                                        label: 'Track new and returning users',
                                        icon: <IconGraduationCap />,
                                        to: 'https://posthog.com/tutorials/track-new-returning-users',
                                        targetBlank: true,
                                    },
                                ]}
                            />
                        </div>
                    </div>
                    <div>
                        <SubsectionHeader title="PostHog, wherever you work" />
                        <div className="grid grid-cols-1 @3xl/main-content:grid-cols-3 gap-4">
                            <LearnCard
                                icon={<IconLogomark />}
                                title="PostHog Code"
                                description="An AI coding agent that knows your product data. Fix errors, ship features, and query PostHog straight from your editor or terminal."
                                buttonLabel="Get PostHog Code"
                                to="https://posthog.com/code"
                                targetBlank
                                action="open_posthog_code"
                            />
                            <LearnCard
                                icon={<IconSlack />}
                                title="Slack app"
                                description="Ask PostHog AI questions and get insights, alerts, and replies without leaving Slack."
                                buttonLabel="Add to Slack"
                                to="https://posthog.com/slack"
                                targetBlank
                                action="open_slack_app"
                            />
                            <LearnCard
                                icon={<IconTerminal />}
                                title="MCP server"
                                description="Connect Claude, Cursor, and other AI assistants to your PostHog data with a single command."
                                buttonLabel="Set up MCP"
                                to="https://posthog.com/docs/model-context-protocol"
                                targetBlank
                                action="open_mcp_docs"
                            />
                        </div>
                    </div>
                    <PublicationsSection />
                </div>
            </section>

            <TaskGuidanceModal />
            <ToolSetupModal installationComplete={installationComplete} />
        </SceneContent>
    )
}

export default Quickstart
