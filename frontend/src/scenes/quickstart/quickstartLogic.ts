import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { addProductIntent } from 'lib/utils/product-intents'
import type { HealthIssuesResponse } from 'scenes/health/healthSceneLogic'
import type { HealthIssue } from 'scenes/health/types'
import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { availableOnboardingProducts, toSentenceCase } from 'scenes/onboarding/shared/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import type { CyclotronJobFiltersType, OnboardingProduct, TeamPublicType, TeamType } from '~/types'

import { ERROR_TRACKING_SUB_TEMPLATE_IDS } from 'products/error_tracking/frontend/scenes/ErrorTrackingConfigurationScene/alerting/alertWizardConfig'

import { PublicationFeedKey, QuickstartPublication, fetchPublicationsPage } from './publications'
import type { quickstartLogicType } from './quickstartLogicType'

/** How far along the activation ladder a tool is. Quality lives past 'live', not as extra levels. */
export type QuickstartToolLevel = 'needs_setup' | 'ready' | 'live'

/** Which primary action the card should offer */
export type QuickstartToolCta = 'install' | 'enable' | 'setup' | 'open'

export type QuickstartTaskAction = 'setup' | 'enable' | 'open_product' | 'open_url' | 'docs'

export type QuickstartCompanionSetup = 'slack' | 'mcp'

export interface QuickstartTaskGuide {
    description: string
    instructions: string[]
    action: QuickstartTaskAction
    actionLabel: string
    url?: string
}

/** Event-derived counters for the last 30 days */
export interface QuickstartToolSignals {
    totalEvents: number
    prodEvents: number
    customEvents: number
    distinctCustomEvents: number
    identifyCalls: number
    exceptions: number
    serverExceptions: number
    backendEvents: number
    flagCalls: number
    prodFlagCalls: number
    pageviews: number
    prodPageviews: number
    surveyResponses: number
    aiGenerations: number
    aiTraceEvents: number
    mcpInitialize: number
    mcpToolCalls: number
}

const EMPTY_TOOL_SIGNALS: QuickstartToolSignals = {
    totalEvents: 0,
    prodEvents: 0,
    customEvents: 0,
    distinctCustomEvents: 0,
    identifyCalls: 0,
    exceptions: 0,
    serverExceptions: 0,
    backendEvents: 0,
    flagCalls: 0,
    prodFlagCalls: 0,
    pageviews: 0,
    prodPageviews: 0,
    surveyResponses: 0,
    aiGenerations: 0,
    aiTraceEvents: 0,
    mcpInitialize: 0,
    mcpToolCalls: 0,
}

/** Non-event facts: resource counts and dedicated proof-of-life checks. Null while unknown. */
export interface QuickstartResources {
    replayRecordings: number | null
    hasLogs: boolean | null
    sourcesCount: number | null
    workflowsCount: number | null
    eventTriggeredWorkflows: number | null
    symbolSetsCount: number | null
    errorAlertsCount: number | null
    ticketsCount: number | null
}

const EMPTY_RESOURCES: QuickstartResources = {
    replayRecordings: null,
    hasLogs: null,
    sourcesCount: null,
    workflowsCount: null,
    eventTriggeredWorkflows: null,
    symbolSetsCount: null,
    errorAlertsCount: null,
    ticketsCount: null,
}

// The same hog function filters the error tracking alerting scene lists: an alert exists
// when a destination matches one of the product's alert sub-templates
const ERROR_TRACKING_ALERT_FILTERS = ERROR_TRACKING_SUB_TEMPLATE_IDS.map(getFiltersFromSubTemplateId).filter(
    (filters): filters is CyclotronJobFiltersType => !!filters
)

export interface QuickstartActivationData {
    signals: QuickstartToolSignals | null
    resources: QuickstartResources
}

interface StatusContext {
    team: TeamType
    signals: QuickstartToolSignals
    resources: QuickstartResources
    healthIssues: HealthIssue[] | null
}

/**
 * One rung of a tool's ladder. Activation rungs take the tool from nothing to live;
 * quality rungs deepen the data past that. The label doubles as the card's next step.
 */
interface ToolMilestone {
    key: string
    label: string
    achieved: (ctx: StatusContext) => boolean
    applies?: (ctx: StatusContext) => boolean
    recommended?: boolean
    guide: QuickstartTaskGuide
}

export interface QuickstartJourneyStep {
    key: string
    label: string
    kind: 'activation' | 'quality'
    achieved: boolean
    recommended?: boolean
    guide: QuickstartTaskGuide
}

export interface QuickstartToolStatus {
    level: QuickstartToolLevel
    /** The full ladder, activation rungs first, shown as setup details rather than completion progress */
    journey: QuickstartJourneyStep[]
    /** The best current improvement, activation first, then quality. Null when none is suggested. */
    nextStep: QuickstartJourneyStep | null
    /** The tool's headline number, e.g. sources connected or custom events captured */
    stat: { value: number; label: string } | null
    cta: QuickstartToolCta
}

export interface QuickstartProduct {
    key: ProductKey
    name: string
    description: string
    icon: string
    iconColor: string
    /** Short audience hint rendered as "Best for …" on the card */
    bestFor: string
    status: QuickstartToolStatus
    /** Whether the setup dialog with SDK instructions applies */
    requiresEvents: boolean
    /** Where "Open" points */
    url: string
    /** Where "Set up" points when the tool has a setup flow */
    setupUrl: string
    docsUrl?: string
}

export interface QuickstartTaskGuidanceSelection {
    productKey: ProductKey
    stepKey: string
}

export interface QuickstartSelectedTask {
    product: QuickstartProduct
    step: QuickstartJourneyStep
}

interface QuickstartProductDefinition {
    bestFor: string
    docsUrl?: string
    /** Overrides the onboarding metadata copy when the quickstart card needs different framing */
    description?: string
    /** Team settings patched to turn the tool on in one click, with the predicate proving it's on */
    optInPayload?: Partial<TeamType>
    enabled?: (team: TeamType) => boolean
    /** The tool is pointless without SDK events, so its setup dialog shows install instructions */
    requiresEvents?: boolean
    /** Usable from day one with nothing configured (workflows, warehouse) — never below 'ready' */
    usableByDefault?: boolean
    /** Ordered rungs from nothing to live. The LAST rung is the proof-of-life signal. */
    activation: ToolMilestone[]
    /** Ordered rungs that deepen the data once live */
    quality: ToolMilestone[]
    stat?: (ctx: StatusContext) => { value: number; label: string } | null
}

export function orderJourneyAchievements(journey: QuickstartJourneyStep[], live: boolean): QuickstartJourneyStep[] {
    let activationBlocked = false
    let qualityBlocked = !live

    return journey.map((step) => {
        if (step.kind === 'activation') {
            const achieved = live || (!activationBlocked && step.achieved)
            activationBlocked ||= !step.achieved
            return { ...step, achieved }
        }

        const achieved = !qualityBlocked && step.achieved
        qualityBlocked ||= !step.achieved
        return { ...step, achieved }
    })
}

function deriveToolStatus(definition: QuickstartProductDefinition, ctx: StatusContext): QuickstartToolStatus {
    const signalRung = definition.activation[definition.activation.length - 1]
    const earlierRungs = definition.activation.slice(0, -1)
    // The signal always wins: real data proves the tool works even if a setup rung
    // looks incomplete (e.g. server-side exceptions without the browser opt-in)
    const live = signalRung.achieved(ctx)

    let level: QuickstartToolLevel
    if (live) {
        level = 'live'
    } else if (earlierRungs.every((rung) => rung.achieved(ctx))) {
        level = 'ready'
    } else {
        level = definition.usableByDefault ? 'ready' : 'needs_setup'
    }

    const rawJourney: QuickstartJourneyStep[] = [
        ...definition.activation.map((rung) => ({
            key: rung.key,
            label: rung.label,
            kind: 'activation' as const,
            achieved: rung.achieved(ctx),
            guide: rung.guide,
        })),
        ...definition.quality
            .filter((rung) => rung.applies?.(ctx) ?? true)
            .map((rung) => ({
                key: rung.key,
                label: rung.label,
                kind: 'quality' as const,
                achieved: rung.achieved(ctx),
                recommended: rung.recommended,
                guide: rung.guide,
            })),
    ]
    const journey = orderJourneyAchievements(rawJourney, live)
    const nextStep = live
        ? (journey.find((step) => step.kind === 'quality' && !step.achieved && step.recommended) ??
          journey.find((step) => step.kind === 'quality' && !step.achieved) ??
          null)
        : (journey.find((step) => step.kind === 'activation' && !step.achieved) ?? null)

    let cta: QuickstartToolCta
    if (definition.requiresEvents && !ctx.team.ingested_event) {
        cta = 'install'
    } else if (definition.optInPayload && definition.enabled && !definition.enabled(ctx.team)) {
        cta = 'enable'
    } else if (level === 'needs_setup') {
        cta = 'setup'
    } else {
        cta = 'open'
    }

    const stat = definition.stat?.(ctx) ?? null
    return {
        level,
        journey,
        nextStep,
        stat: stat && stat.value > 0 ? stat : null,
        cta,
    }
}

/** Display order: the tools most teams start with come first. */
export const QUICKSTART_PRODUCT_ORDER: ProductKey[] = [
    ProductKey.PRODUCT_ANALYTICS,
    ProductKey.WEB_ANALYTICS,
    ProductKey.SESSION_REPLAY,
    ProductKey.ERROR_TRACKING,
    ProductKey.FEATURE_FLAGS,
    ProductKey.SURVEYS,
    ProductKey.EXPERIMENTS,
    ProductKey.AI_OBSERVABILITY,
    ProductKey.DATA_WAREHOUSE,
    ProductKey.WORKFLOWS,
    ProductKey.LOGS,
    ProductKey.MCP_ANALYTICS,
    ProductKey.CONVERSATIONS,
]

// Shared rungs. Each is a plain predicate over the context, so ladders can reuse them freely.
const installAnySdk: ToolMilestone = {
    key: 'install_sdk',
    label: 'Install a PostHog SDK',
    achieved: ({ team }) => !!team.ingested_event,
    guide: {
        description: 'Connect your app to PostHog so it can start sending data.',
        instructions: [
            'Choose the SDK for your framework or language.',
            'Add your project token and initialize PostHog.',
            'Run your app and send a test event.',
        ],
        action: 'setup',
        actionLabel: 'Choose an SDK',
    },
}
const installWebSdk: ToolMilestone = {
    key: 'install_web_sdk',
    label: 'Install posthog-js on your site',
    achieved: ({ team }) => !!team.ingested_event,
    guide: {
        description: 'Add the PostHog web SDK to start capturing activity from your site.',
        instructions: [
            'Choose your web framework.',
            'Add the generated install snippet to your app.',
            'Load your site and confirm an event arrives.',
        ],
        action: 'setup',
        actionLabel: 'Open web setup',
    },
}
const productionTraffic: ToolMilestone = {
    key: 'production_traffic',
    label: 'Deploy your instrumentation to production',
    achieved: ({ signals }) => signals.prodEvents > 0,
    guide: {
        description: 'Move the same PostHog setup you tested locally into your production deployment.',
        instructions: [
            'Make your PostHog configuration available in production.',
            'Deploy the instrumented version of your app.',
            'Use the production app once, then return here after data arrives.',
        ],
        action: 'setup',
        actionLabel: 'Review setup',
    },
}
const firstCustomEvent: ToolMilestone = {
    key: 'first_custom_event',
    label: 'Capture your first custom event',
    achieved: ({ signals }) => signals.customEvents > 0,
    guide: {
        description: 'Track a meaningful action that is specific to your product.',
        instructions: [
            'Pick one user action you want to measure.',
            'Call posthog.capture with a clear event name when it happens.',
            'Trigger the action once and confirm the event appears in PostHog.',
        ],
        action: 'docs',
        actionLabel: 'View capture guide',
        url: 'https://posthog.com/docs/product-analytics/capture-events',
    },
}

const QUICKSTART_PRODUCT_DEFINITIONS: Partial<Record<ProductKey, QuickstartProductDefinition>> = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        bestFor: 'understanding user behavior',
        docsUrl: 'https://posthog.com/docs/product-analytics',
        requiresEvents: true,
        activation: [
            installAnySdk,
            {
                key: 'events',
                label: 'Capture your first event',
                achieved: ({ signals }) => signals.totalEvents > 0,
                guide: {
                    description: 'Send one event from your app to confirm the SDK is connected.',
                    instructions: [
                        'Open the SDK setup for your framework.',
                        'Run your app with PostHog initialized.',
                        'Interact with the app or capture a test event.',
                    ],
                    action: 'setup',
                    actionLabel: 'Open SDK setup',
                },
            },
        ],
        quality: [
            productionTraffic,
            firstCustomEvent,
            {
                key: 'custom_breadth',
                label: 'Track 5+ distinct custom events',
                achieved: ({ signals }) => signals.distinctCustomEvents >= 5,
                guide: {
                    description: 'Build a useful event vocabulary around the main actions in your product.',
                    instructions: [
                        'List the key actions in your activation and retention paths.',
                        'Capture each action with a stable, descriptive event name.',
                        'Add properties that explain the context of each action.',
                    ],
                    action: 'docs',
                    actionLabel: 'Plan your events',
                    url: 'https://posthog.com/docs/product-analytics/capture-events',
                },
            },
            {
                key: 'identify',
                label: 'Identify your users to unlock person-level analysis',
                achieved: ({ signals }) => signals.identifyCalls > 0,
                guide: {
                    description: 'Associate anonymous activity with the people using your product.',
                    instructions: [
                        'Choose a stable unique ID from your own user database.',
                        'Call posthog.identify after the user signs in.',
                        'Include useful person properties such as plan or company.',
                    ],
                    action: 'docs',
                    actionLabel: 'View identify guide',
                    url: 'https://posthog.com/docs/product-analytics/identify',
                },
            },
        ],
        stat: ({ signals }) => ({ value: signals.distinctCustomEvents, label: 'custom events' }),
    },
    [ProductKey.WEB_ANALYTICS]: {
        bestFor: 'marketing & traffic',
        docsUrl: 'https://posthog.com/docs/web-analytics',
        requiresEvents: true,
        activation: [
            installWebSdk,
            {
                key: 'pageviews',
                label: 'Get pageviews flowing',
                achieved: ({ signals }) => signals.pageviews > 0,
                guide: {
                    description: 'Confirm the web SDK is capturing visits to your site.',
                    instructions: [
                        'Install posthog-js with pageview capture enabled.',
                        'Open a page in your instrumented site.',
                        'Check web analytics after the pageview arrives.',
                    ],
                    action: 'setup',
                    actionLabel: 'Open web setup',
                },
            },
        ],
        quality: [
            {
                key: 'prod_pageviews',
                label: 'Deploy to production to see real visitors',
                achieved: ({ signals }) => signals.prodPageviews > 0,
                guide: productionTraffic.guide,
            },
            { ...firstCustomEvent, label: 'Capture custom events to measure conversions' },
            {
                key: 'authorized_urls',
                label: 'Add your web analytics domains',
                achieved: () => false,
                applies: ({ healthIssues }) => healthIssues?.some((issue) => issue.kind === 'authorized_urls') ?? false,
                recommended: true,
                guide: {
                    description:
                        'Add the domains where your site runs so web analytics filters and toolbar links use the right URLs.',
                    instructions: [
                        'Open Settings and select Web analytics.',
                        'Under Web analytics domains, add the full URL for each production domain.',
                        'Save your changes. This recommendation will disappear after PostHog checks the project again.',
                    ],
                    action: 'open_url',
                    actionLabel: 'Configure domains',
                    url: urls.settings('environment-web-analytics', 'web-analytics-authorized-urls'),
                },
            },
        ],
        stat: ({ signals }) => ({ value: signals.pageviews, label: 'pageviews · 30d' }),
    },
    [ProductKey.SESSION_REPLAY]: {
        bestFor: 'debugging UX issues',
        docsUrl: 'https://posthog.com/docs/session-replay',
        requiresEvents: true,
        // Same payload the replay onboarding step applies
        optInPayload: {
            session_recording_opt_in: true,
            capture_console_log_opt_in: true,
            capture_performance_opt_in: true,
        },
        enabled: (team) => !!team.session_recording_opt_in,
        activation: [
            installWebSdk,
            {
                key: 'opt_in',
                label: 'Turn on session recordings',
                achieved: ({ team }) => !!team.session_recording_opt_in,
                guide: {
                    description: 'Enable recording, console logs, and performance capture for this project.',
                    instructions: [
                        'Turn on session replay for the project.',
                        'Open your instrumented app in a new session.',
                        'Use the app for a minute so PostHog can create a recording.',
                    ],
                    action: 'enable',
                    actionLabel: 'Enable session replay',
                },
            },
            {
                key: 'recordings',
                label: 'Record your first session',
                achieved: ({ resources }) => (resources.replayRecordings ?? 0) > 0,
                guide: {
                    description: 'Generate a real session so you can verify replay quality.',
                    instructions: [
                        'Open your instrumented app in a fresh browser session.',
                        'Navigate through a few screens and interact with the UI.',
                        'Wait for the session to end, then open session replay.',
                    ],
                    action: 'open_product',
                    actionLabel: 'Open session replay',
                },
            },
        ],
        quality: [
            {
                key: 'console_logs',
                label: 'Capture console logs with recordings',
                achieved: ({ team }) => !!team.capture_console_log_opt_in,
                guide: {
                    description: 'Include browser console output to add debugging context to replays.',
                    instructions: [
                        'Enable console log capture for session replay.',
                        'Start a new recorded session.',
                        'Open the replay and inspect the console panel.',
                    ],
                    action: 'enable',
                    actionLabel: 'Enable console logs',
                },
            },
            {
                key: 'performance',
                label: 'Capture network performance with recordings',
                achieved: ({ team }) => !!team.capture_performance_opt_in,
                guide: {
                    description: 'Include network timing so slow requests are visible beside the replay.',
                    instructions: [
                        'Enable performance capture for session replay.',
                        'Start a new recorded session.',
                        'Open the replay and inspect network activity.',
                    ],
                    action: 'enable',
                    actionLabel: 'Enable performance capture',
                },
            },
            productionTraffic,
        ],
        stat: ({ resources }) => ({ value: resources.replayRecordings ?? 0, label: 'recordings · 30d' }),
    },
    [ProductKey.ERROR_TRACKING]: {
        bestFor: 'catching bugs early',
        docsUrl: 'https://posthog.com/docs/error-tracking',
        requiresEvents: true,
        // Browser autocapture only: server SDKs capture exceptions without this opt-in
        optInPayload: { autocapture_exceptions_opt_in: true },
        enabled: (team) => !!team.autocapture_exceptions_opt_in,
        activation: [
            installAnySdk,
            {
                key: 'exceptions',
                label: 'Capture your first exception',
                achieved: ({ signals }) => signals.exceptions > 0,
                guide: {
                    description: 'Send one handled or unhandled exception to verify error tracking.',
                    instructions: [
                        'Open the setup instructions for your SDK.',
                        'Enable exception capture or send a test exception.',
                        'Open error tracking after the exception arrives.',
                    ],
                    action: 'setup',
                    actionLabel: 'Open error setup',
                },
            },
        ],
        quality: [
            {
                key: 'web_autocapture',
                label: 'Turn on exception autocapture for the web',
                achieved: ({ team }) => !!team.autocapture_exceptions_opt_in,
                guide: {
                    description: 'Automatically capture unhandled browser errors and promise rejections.',
                    instructions: [
                        'Enable exception autocapture for the project.',
                        'Deploy the setting with your web SDK.',
                        'Trigger a safe test error and verify it appears.',
                    ],
                    action: 'enable',
                    actionLabel: 'Enable autocapture',
                },
            },
            {
                key: 'server_exceptions',
                label: 'Capture exceptions from a server SDK too',
                achieved: ({ signals }) => signals.serverExceptions > 0,
                guide: {
                    description: 'Add backend exceptions so errors can be traced across your stack.',
                    instructions: [
                        'Choose the SDK for your backend language.',
                        'Configure exception capture in the server process.',
                        'Send a safe test exception from a non-production request.',
                    ],
                    action: 'setup',
                    actionLabel: 'Choose a server SDK',
                },
            },
            {
                key: 'source_maps',
                label: 'Upload source maps for readable stack traces',
                achieved: ({ resources }) => (resources.symbolSetsCount ?? 0) > 0,
                guide: {
                    description:
                        'Upload source maps during deployment so minified browser stacks resolve to your source code.',
                    instructions: [
                        'Generate source maps in your production build.',
                        'Upload them with the PostHog CLI during deployment.',
                        'Verify a new exception shows readable file names and lines.',
                    ],
                    action: 'docs',
                    actionLabel: 'View source map guide',
                    url: 'https://posthog.com/docs/error-tracking/upload-source-maps',
                },
            },
            {
                key: 'alert',
                label: 'Set up an alert for new exceptions',
                achieved: ({ resources }) => (resources.errorAlertsCount ?? 0) > 0,
                guide: {
                    description: 'Notify your team when an important new exception appears.',
                    instructions: [
                        'Open error tracking and choose an alert destination.',
                        'Select which new or recurring exceptions should notify you.',
                        'Send a test notification before saving the alert.',
                    ],
                    action: 'open_product',
                    actionLabel: 'Open error tracking',
                },
            },
            productionTraffic,
        ],
        stat: ({ signals }) => ({ value: signals.exceptions, label: 'exceptions · 30d' }),
    },
    [ProductKey.FEATURE_FLAGS]: {
        bestFor: 'safe rollouts',
        docsUrl: 'https://posthog.com/docs/feature-flags',
        requiresEvents: true,
        activation: [
            installAnySdk,
            {
                key: 'flag_called',
                label: 'Create a flag and call it from your code',
                achieved: ({ signals }) => signals.flagCalls > 0,
                guide: {
                    description: 'Create a feature flag, add its key to your app, and evaluate it once.',
                    instructions: [
                        'Create a flag and choose its initial rollout conditions.',
                        'Copy the generated code for your SDK.',
                        'Run the code once and confirm the evaluation appears.',
                    ],
                    action: 'open_product',
                    actionLabel: 'Create a feature flag',
                },
            },
        ],
        quality: [
            {
                key: 'prod_flag_calls',
                label: 'Evaluate flags in production',
                achieved: ({ signals }) => signals.prodFlagCalls > 0,
                guide: {
                    description: 'Deploy your flag evaluation so real users can enter the rollout.',
                    instructions: [
                        'Add the flag check to the production code path.',
                        'Deploy the change with the same project configuration.',
                        'Confirm production evaluations appear in PostHog.',
                    ],
                    action: 'docs',
                    actionLabel: 'View implementation guide',
                    url: 'https://posthog.com/docs/feature-flags/installation',
                },
            },
        ],
        stat: ({ signals }) => ({ value: signals.flagCalls, label: 'flag calls · 30d' }),
    },
    [ProductKey.SURVEYS]: {
        bestFor: 'user feedback',
        docsUrl: 'https://posthog.com/docs/surveys',
        requiresEvents: true,
        optInPayload: { surveys_opt_in: true },
        enabled: (team) => !!team.surveys_opt_in,
        activation: [
            installWebSdk,
            {
                key: 'opt_in',
                label: 'Turn on surveys',
                achieved: ({ team }) => !!team.surveys_opt_in,
                guide: {
                    description: 'Enable surveys for the project so they can be shown in your app.',
                    instructions: [
                        'Turn on surveys for this project.',
                        'Confirm the web SDK is installed.',
                        'Create a survey and preview it before launch.',
                    ],
                    action: 'enable',
                    actionLabel: 'Enable surveys',
                },
            },
            {
                key: 'responses',
                label: 'Launch a survey and collect your first response',
                achieved: ({ signals }) => signals.surveyResponses > 0,
                guide: {
                    description: 'Publish a focused survey and collect one real response.',
                    instructions: [
                        'Create a survey with one clear question.',
                        'Choose who should see it and publish it.',
                        'Answer it once in your instrumented app to verify the flow.',
                    ],
                    action: 'open_product',
                    actionLabel: 'Create a survey',
                },
            },
        ],
        quality: [{ ...productionTraffic, label: 'Collect responses from production traffic' }],
        stat: ({ signals }) => ({ value: signals.surveyResponses, label: 'responses · 30d' }),
    },
    [ProductKey.EXPERIMENTS]: {
        bestFor: 'A/B testing',
        docsUrl: 'https://posthog.com/docs/experiments',
        requiresEvents: true,
        activation: [
            installAnySdk,
            // Experiments require a feature flag: exposure rides on flag evaluations
            {
                key: 'flag_called',
                label: 'Call a feature flag from your code',
                achieved: ({ signals }) => signals.flagCalls > 0,
                guide: {
                    description: 'Use the experiment flag in your app so PostHog can assign variants.',
                    instructions: [
                        'Create or open an experiment and copy its feature flag key.',
                        'Evaluate the flag where the tested experience is rendered.',
                        'Run the code once and verify an exposure is captured.',
                    ],
                    action: 'open_product',
                    actionLabel: 'Open experiments',
                },
            },
        ],
        quality: [
            { ...firstCustomEvent, label: 'Track your goal metric with a custom event' },
            {
                key: 'prod_flag_calls',
                label: 'Run experiments on production traffic',
                achieved: ({ signals }) => signals.prodFlagCalls > 0,
                guide: {
                    description: 'Ship the experiment code path so real users can be assigned to variants.',
                    instructions: [
                        'Confirm the experiment flag controls the intended experience.',
                        'Deploy the change to production.',
                        'Check that exposures and goal events arrive before interpreting results.',
                    ],
                    action: 'open_product',
                    actionLabel: 'Open experiments',
                },
            },
        ],
    },
    [ProductKey.AI_OBSERVABILITY]: {
        bestFor: 'LLM-powered apps',
        docsUrl: 'https://posthog.com/docs/llm-analytics',
        activation: [
            {
                key: 'server_sdk',
                label: 'Install a server SDK',
                achieved: ({ signals }) => signals.backendEvents > 0,
                guide: {
                    description: 'Install PostHog in the service that makes your LLM calls.',
                    instructions: [
                        'Choose the SDK for your backend language.',
                        'Initialize it with your project token.',
                        'Run the service and confirm it can send an event.',
                    ],
                    action: 'setup',
                    actionLabel: 'Choose a server SDK',
                },
            },
            {
                key: 'ai_events',
                label: 'Wrap your LLM calls to capture generations',
                achieved: ({ signals }) => signals.aiGenerations + signals.aiTraceEvents > 0,
                guide: {
                    description:
                        'Instrument the LLM call so prompts, responses, latency, and cost are captured together.',
                    instructions: [
                        'Open the setup for your model provider and SDK.',
                        'Wrap the LLM client or capture a generation explicitly.',
                        'Make one test request and inspect the generation in PostHog.',
                    ],
                    action: 'setup',
                    actionLabel: 'Open LLM setup',
                },
            },
        ],
        quality: [
            {
                key: 'traces',
                label: 'Capture full traces, not just generations',
                achieved: ({ signals }) => signals.aiTraceEvents > 0,
                guide: {
                    description:
                        'Group generations and application work into traces so the full request can be debugged.',
                    instructions: [
                        'Start a trace when the AI request enters your app.',
                        'Attach generations and spans to the same trace ID.',
                        'End the trace after the user-visible response is ready.',
                    ],
                    action: 'docs',
                    actionLabel: 'View tracing guide',
                    url: 'https://posthog.com/docs/llm-analytics',
                },
            },
        ],
        stat: ({ signals }) => ({
            value: signals.aiGenerations + signals.aiTraceEvents,
            label: 'AI events · 30d',
        }),
    },
    [ProductKey.DATA_WAREHOUSE]: {
        bestFor: 'joining external data',
        docsUrl: 'https://posthog.com/docs/data-warehouse',
        usableByDefault: true,
        activation: [
            {
                key: 'first_source',
                label: 'Connect your first source',
                achieved: ({ resources }) => (resources.sourcesCount ?? 0) > 0,
                guide: {
                    description: 'Connect a database or SaaS source so its data is available in PostHog.',
                    instructions: [
                        'Choose the source you want to connect.',
                        'Enter credentials with the narrowest required permissions.',
                        'Select the tables and start the first sync.',
                    ],
                    action: 'open_product',
                    actionLabel: 'Connect a source',
                },
            },
        ],
        quality: [
            {
                key: 'second_source',
                label: 'Connect a second source to join across systems',
                achieved: ({ resources }) => (resources.sourcesCount ?? 0) >= 2,
                guide: {
                    description: 'Add another source so product activity can be joined with business data.',
                    instructions: [
                        'Choose a source that adds useful context to your product data.',
                        'Connect it with read-only credentials where possible.',
                        'Create a model or query that joins the two systems.',
                    ],
                    action: 'open_product',
                    actionLabel: 'Connect another source',
                },
            },
        ],
        stat: ({ resources }) => ({ value: resources.sourcesCount ?? 0, label: 'sources connected' }),
    },
    [ProductKey.WORKFLOWS]: {
        bestFor: 'automations & messaging',
        description: 'Automate messages and actions. No install needed, though it works best with events flowing.',
        usableByDefault: true,
        activation: [
            {
                key: 'first_workflow',
                label: 'Create your first workflow',
                achieved: ({ resources }) => (resources.workflowsCount ?? 0) > 0,
                guide: {
                    description: 'Automate one useful message or action from a product signal.',
                    instructions: [
                        'Choose a workflow template or start from scratch.',
                        'Add a trigger and the action it should run.',
                        'Test the workflow before turning it on.',
                    ],
                    action: 'open_product',
                    actionLabel: 'Create a workflow',
                },
            },
        ],
        quality: [
            {
                key: 'event_trigger',
                label: 'Trigger a workflow from an event',
                achieved: ({ resources }) => (resources.eventTriggeredWorkflows ?? 0) > 0,
                guide: {
                    description: 'Start a workflow when a meaningful event happens in your product.',
                    instructions: [
                        'Open a workflow and add an event trigger.',
                        'Choose the event and any property filters.',
                        'Trigger the event once and inspect the test run.',
                    ],
                    action: 'open_product',
                    actionLabel: 'Open workflows',
                },
            },
            { ...firstCustomEvent, label: 'Capture custom events for smarter triggers' },
        ],
        stat: ({ resources }) => ({ value: resources.workflowsCount ?? 0, label: 'workflows' }),
    },
    [ProductKey.LOGS]: {
        bestFor: 'backend debugging',
        docsUrl: 'https://posthog.com/docs/logs',
        activation: [
            {
                key: 'logs_flowing',
                label: 'Point your OpenTelemetry logs at PostHog',
                achieved: ({ resources }) => resources.hasLogs === true,
                guide: {
                    description: 'Send OpenTelemetry logs from your service to the PostHog ingestion endpoint.',
                    instructions: [
                        'Choose your OpenTelemetry collector or SDK.',
                        'Configure the PostHog logs endpoint and authentication.',
                        'Emit a test log and confirm it appears in the logs explorer.',
                    ],
                    action: 'setup',
                    actionLabel: 'Open logs setup',
                },
            },
        ],
        quality: [],
    },
    [ProductKey.MCP_ANALYTICS]: {
        bestFor: 'MCP server owners',
        activation: [
            {
                key: 'instrumented',
                label: 'Instrument your MCP server',
                achieved: ({ signals }) => signals.mcpInitialize > 0 || signals.mcpToolCalls > 0,
                guide: {
                    description:
                        'Add PostHog instrumentation to your MCP server so sessions and tool calls can be analyzed.',
                    instructions: [
                        'Open the MCP analytics setup guide.',
                        'Add instrumentation around server initialization and tool execution.',
                        'Connect a client once and confirm the session appears.',
                    ],
                    action: 'setup',
                    actionLabel: 'Open MCP setup',
                },
            },
            {
                key: 'tool_calls',
                label: 'See real tool calls come in',
                achieved: ({ signals }) => signals.mcpToolCalls > 0,
                guide: {
                    description: 'Run a real MCP tool through an instrumented client connection.',
                    instructions: [
                        'Connect your MCP server to a client.',
                        'Ask the client to invoke one of your tools.',
                        'Open MCP analytics and inspect the captured call.',
                    ],
                    action: 'open_product',
                    actionLabel: 'Open MCP analytics',
                },
            },
        ],
        quality: [
            {
                // The product's own dashboard graduates to its metrics view around this volume
                key: 'volume',
                label: 'Reach 300 tool calls to unlock usage metrics',
                achieved: ({ signals }) => signals.mcpToolCalls >= 300,
                guide: {
                    description:
                        'Keep real traffic instrumented until there is enough usage to show stable tool-level patterns.',
                    instructions: [
                        'Verify all production tool calls use the instrumented path.',
                        'Use MCP analytics to watch call volume grow.',
                        'Review usage metrics after enough real calls have arrived.',
                    ],
                    action: 'open_product',
                    actionLabel: 'View tool calls',
                },
            },
        ],
        stat: ({ signals }) => ({ value: signals.mcpToolCalls, label: 'tool calls · 30d' }),
    },
    [ProductKey.CONVERSATIONS]: {
        bestFor: 'customer support',
        // Admin-gated team field: the enable listener explains the permission on a 403
        optInPayload: { conversations_enabled: true },
        enabled: (team) => !!team.conversations_enabled,
        activation: [
            {
                key: 'enabled',
                label: 'Turn on Support',
                achieved: ({ team }) => !!team.conversations_enabled,
                guide: {
                    description: 'Enable Support for this project so your team can receive and manage tickets.',
                    instructions: [
                        'Turn on Support for the project.',
                        'Open the inbox and choose a channel to connect.',
                        'Send a test message through the connected channel.',
                    ],
                    action: 'enable',
                    actionLabel: 'Enable Support',
                },
            },
            {
                key: 'first_ticket',
                label: 'Connect a channel and receive your first ticket',
                achieved: ({ resources }) => (resources.ticketsCount ?? 0) > 0,
                guide: {
                    description: 'Connect a customer channel and verify the first conversation reaches your inbox.',
                    instructions: [
                        'Open Support and connect a channel.',
                        'Complete the channel-specific installation.',
                        'Send a test message and confirm a ticket is created.',
                    ],
                    action: 'open_product',
                    actionLabel: 'Open Support',
                },
            },
        ],
        quality: [],
        stat: ({ resources }) => ({ value: resources.ticketsCount ?? 0, label: 'tickets' }),
    },
}

const isFullTeam = (team: TeamType | TeamPublicType | null): team is TeamType =>
    !!team && 'has_completed_onboarding_for' in team

// The scene is many users' homepage, so it can remount on every "Home" click. The signals
// query aggregates 30 days of events — too expensive to re-run per mount, and statuses
// don't need to be fresher than a few minutes.
const ACTIVATION_DATA_CACHE_TTL_MS = 5 * 60 * 1000
let activationDataCache: { teamId: number; fetchedAt: number; data: QuickstartActivationData } | null = null

/** The cache outlives logic mounts by design; stories and tests switching mock data must drop it. */
export function clearQuickstartActivationCache(): void {
    activationDataCache = null
}

function buildProduct(key: ProductKey, ctx: StatusContext): QuickstartProduct | null {
    const definition = QUICKSTART_PRODUCT_DEFINITIONS[key]
    const meta = (availableOnboardingProducts as Partial<Record<ProductKey, OnboardingProduct>>)[key]
    if (!definition || !meta) {
        return null
    }
    return {
        key,
        name: toSentenceCase(meta.name),
        description: definition.description ?? meta.userCentricDescription ?? meta.description,
        icon: meta.icon,
        iconColor: meta.iconColor,
        bestFor: definition.bestFor,
        status: deriveToolStatus(definition, ctx),
        requiresEvents: !!definition.requiresEvents,
        url: meta.url,
        setupUrl: urls.onboarding({ productKey: key }),
        docsUrl: definition.docsUrl,
    }
}

export function getQuickstartTrackingProperties(
    team: TeamType,
    products: QuickstartProduct[]
): Record<string, unknown> {
    const onboardedProducts = Object.entries(team.has_completed_onboarding_for ?? {})
        .filter(([, completed]) => completed)
        .map(([productKey]) => productKey)
    const liveProducts = products.filter((product) => product.status.level === 'live').map((product) => product.key)
    const isPostOnboarding = team.completed_snippet_onboarding || onboardedProducts.length > 0

    return {
        is_post_onboarding: isPostOnboarding,
        has_ingested_event: team.ingested_event,
        onboarded_products: onboardedProducts,
        live_products: liveProducts,
        live_product_count: liveProducts.length,
    }
}

export const quickstartLogic = kea<quickstartLogicType>([
    path(['scenes', 'quickstart', 'quickstartLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions({
        enableProduct: (productKey: ProductKey) => ({ productKey }),
        productEnableFinished: (productKey: ProductKey) => ({ productKey }),
        openToolSetupModal: (productKey: ProductKey) => ({ productKey }),
        closeToolSetupModal: true,
        openTaskGuidance: (productKey: ProductKey, stepKey: string) => ({ productKey, stepKey }),
        closeTaskGuidance: true,
        openCompanionSetup: (companion: QuickstartCompanionSetup) => ({ companion }),
        closeCompanionSetup: true,
        setPublicationsHasMore: (feed: PublicationFeedKey, hasMore: boolean) => ({ feed, hasMore }),
    }),
    loaders(({ actions, values }) => {
        // Swallow errors: without data the rail simply doesn't render, and a feed
        // hiccup must never toast at a brand-new user.
        const loadFeedPage = async (
            feed: PublicationFeedKey,
            current: QuickstartPublication[]
        ): Promise<QuickstartPublication[]> => {
            if (current.length > 0 && !values.publicationsHasMore[feed]) {
                return current
            }
            try {
                const page = await fetchPublicationsPage(feed, current.length)
                actions.setPublicationsHasMore(feed, page.hasMore)
                if (current.length === 0) {
                    return page.publications
                }
                // The feed can shift between pages (a new post lands), so drop
                // anything already shown instead of rendering duplicate cards
                const seen = new Set(current.map((publication) => publication.url))
                const merged = [...current, ...page.publications.filter((publication) => !seen.has(publication.url))]
                posthog.capture('quickstart publications loaded more', { feed, total: merged.length })
                return merged
            } catch {
                actions.setPublicationsHasMore(feed, false)
                return current
            }
        }
        return {
            activationData: [
                { signals: null, resources: EMPTY_RESOURCES } as QuickstartActivationData,
                {
                    // Every sub-fetch is best-effort: a failure leaves its facts null and the
                    // affected rungs simply read as unachieved
                    loadActivationData: async (): Promise<QuickstartActivationData> => {
                        const teamId = values.currentTeam?.id
                        const cached = activationDataCache
                        if (
                            teamId &&
                            cached &&
                            cached.teamId === teamId &&
                            Date.now() - cached.fetchedAt < ACTIVATION_DATA_CACHE_TTL_MS
                        ) {
                            return cached.data
                        }

                        const queryTags = { scene: 'Quickstart', productKey: 'platform_and_support' } as const
                        // Approximates posthog/models/team/production_event_activation.py: hostless
                        // events count as production only when they come from a server SDK, and
                        // dev hosts include tunnels and reserved TLDs, not just localhost
                        const signalsQuery = hogql`
                            SELECT
                                count() AS total_events,
                                countIf(is_prod) AS prod_events,
                                countIf(is_custom) AS custom_events,
                                uniqIf(event, is_custom) AS distinct_custom_events,
                                countIf(event = '$identify') AS identify_calls,
                                countIf(event = '$exception') AS exceptions,
                                countIf(event = '$exception' AND is_backend) AS server_exceptions,
                                countIf(is_backend) AS backend_events,
                                countIf(event = '$feature_flag_called') AS flag_calls,
                                countIf(event = '$feature_flag_called' AND is_prod) AS prod_flag_calls,
                                countIf(event = '$pageview') AS pageviews,
                                countIf(event = '$pageview' AND is_prod) AS prod_pageviews,
                                countIf(event = 'survey sent') AS survey_responses,
                                countIf(event = '$ai_generation') AS ai_generations,
                                countIf(event IN ('$ai_trace', '$ai_span', '$ai_embedding')) AS ai_trace_events,
                                countIf(event = '$mcp_initialize') AS mcp_initialize,
                                countIf(event = '$mcp_tool_call') AS mcp_tool_calls
                            FROM (
                                SELECT
                                    event,
                                    properties.$lib IN ('posthog-node', 'posthog-python', 'posthog-go', 'posthog-ruby', 'posthog-php', 'posthog-java', 'posthog-dotnet', 'posthog-elixir', 'posthog-rs') AS is_backend,
                                    event NOT LIKE '$%' AND event NOT IN ('survey sent', 'survey shown', 'survey dismissed') AS is_custom,
                                    if(
                                        properties.$host IS NULL,
                                        properties.$lib IN ('posthog-node', 'posthog-python', 'posthog-go', 'posthog-ruby', 'posthog-php', 'posthog-java', 'posthog-dotnet', 'posthog-elixir', 'posthog-rs'),
                                        NOT (
                                            properties.$host LIKE 'localhost%'
                                            OR properties.$host LIKE '127.0.0.1%'
                                            OR properties.$host LIKE '0.0.0.0%'
                                            OR properties.$host LIKE '192.168.%'
                                            OR properties.$host LIKE '%.local'
                                            OR properties.$host LIKE '%.local:%'
                                            OR properties.$host LIKE '%.test'
                                            OR properties.$host LIKE '%.test:%'
                                            OR properties.$host LIKE '%.internal'
                                            OR properties.$host LIKE '%.internal:%'
                                            OR properties.$host LIKE '%.example'
                                            OR properties.$host LIKE '%.example:%'
                                            OR properties.$host LIKE '%.ngrok%'
                                            OR properties.$host LIKE '%.nip.io%'
                                            OR properties.$host LIKE '%.ts.net%'
                                            OR properties.$host LIKE '%.trycloudflare.com%'
                                            OR properties.$host LIKE '%.loca.lt%'
                                        )
                                    ) AS is_prod
                                FROM events
                                WHERE timestamp >= now() - INTERVAL 30 DAY AND timestamp <= now()
                            )`
                        const replayQuery = hogql`
                            SELECT count(DISTINCT session_id)
                            FROM raw_session_replay_events
                            WHERE min_first_timestamp >= now() - INTERVAL 30 DAY`

                        const [
                            signalsResult,
                            replayResult,
                            hasLogsResult,
                            sourcesResult,
                            flowsResult,
                            symbolSetsResult,
                            alertsResult,
                            ticketsResult,
                        ] = await Promise.allSettled([
                            api.queryHogQL(signalsQuery, queryTags),
                            api.queryHogQL(replayQuery, queryTags),
                            api.logs.hasLogs(),
                            api.externalDataSources.list(),
                            api.hogFlows.getHogFlows(),
                            api.errorTracking.symbolSets.list({ offset: 0, limit: 1 }),
                            api.hogFunctions.list({
                                types: ['destination'],
                                filter_groups: ERROR_TRACKING_ALERT_FILTERS,
                                limit: 1,
                            }),
                            api.conversationsTickets.list({ limit: 1 }),
                        ])

                        let signals: QuickstartToolSignals | null = null
                        if (signalsResult.status === 'fulfilled') {
                            const row = signalsResult.value.results?.[0]
                            if (row) {
                                signals = {
                                    totalEvents: Number(row[0]) || 0,
                                    prodEvents: Number(row[1]) || 0,
                                    customEvents: Number(row[2]) || 0,
                                    distinctCustomEvents: Number(row[3]) || 0,
                                    identifyCalls: Number(row[4]) || 0,
                                    exceptions: Number(row[5]) || 0,
                                    serverExceptions: Number(row[6]) || 0,
                                    backendEvents: Number(row[7]) || 0,
                                    flagCalls: Number(row[8]) || 0,
                                    prodFlagCalls: Number(row[9]) || 0,
                                    pageviews: Number(row[10]) || 0,
                                    prodPageviews: Number(row[11]) || 0,
                                    surveyResponses: Number(row[12]) || 0,
                                    aiGenerations: Number(row[13]) || 0,
                                    aiTraceEvents: Number(row[14]) || 0,
                                    mcpInitialize: Number(row[15]) || 0,
                                    mcpToolCalls: Number(row[16]) || 0,
                                }
                            }
                        }

                        const workflows = flowsResult.status === 'fulfilled' ? flowsResult.value.results : null
                        const activeWorkflows = workflows?.filter((flow) => flow.status !== 'archived') ?? null
                        const resources: QuickstartResources = {
                            replayRecordings:
                                replayResult.status === 'fulfilled'
                                    ? Number(replayResult.value.results?.[0]?.[0]) || 0
                                    : null,
                            hasLogs: hasLogsResult.status === 'fulfilled' ? hasLogsResult.value : null,
                            sourcesCount:
                                sourcesResult.status === 'fulfilled'
                                    ? (sourcesResult.value.results?.length ?? 0)
                                    : null,
                            workflowsCount: activeWorkflows ? activeWorkflows.length : null,
                            eventTriggeredWorkflows: activeWorkflows
                                ? activeWorkflows.filter((flow) => flow.trigger?.type === 'event').length
                                : null,
                            symbolSetsCount:
                                symbolSetsResult.status === 'fulfilled'
                                    ? (symbolSetsResult.value.count ?? symbolSetsResult.value.results?.length ?? 0)
                                    : null,
                            errorAlertsCount:
                                alertsResult.status === 'fulfilled'
                                    ? (alertsResult.value.count ?? alertsResult.value.results?.length ?? 0)
                                    : null,
                            ticketsCount:
                                ticketsResult.status === 'fulfilled'
                                    ? (ticketsResult.value.count ?? ticketsResult.value.results?.length ?? 0)
                                    : null,
                        }

                        const data: QuickstartActivationData = { signals, resources }
                        if (teamId) {
                            activationDataCache = { teamId, fetchedAt: Date.now(), data }
                        }
                        return data
                    },
                },
            ],
            healthIssues: [
                null as HealthIssue[] | null,
                {
                    loadHealthIssues: async (): Promise<HealthIssue[] | null> => {
                        const teamId = values.currentTeam?.id
                        if (!teamId) {
                            return null
                        }
                        try {
                            const response = await api.get<HealthIssuesResponse>(
                                `api/environments/${teamId}/health_issues/?status=active&dismissed=false&kind=authorized_urls`
                            )
                            return response.results
                        } catch {
                            return null
                        }
                    },
                },
            ],
            blogPublications: [
                [] as QuickstartPublication[],
                {
                    loadBlogPublications: async (): Promise<QuickstartPublication[]> => await loadFeedPage('blog', []),
                    loadMoreBlogPublications: async (): Promise<QuickstartPublication[]> =>
                        await loadFeedPage('blog', values.blogPublications),
                },
            ],
            newsletterPublications: [
                [] as QuickstartPublication[],
                {
                    loadNewsletterPublications: async (): Promise<QuickstartPublication[]> =>
                        await loadFeedPage('newsletter', []),
                    loadMoreNewsletterPublications: async (): Promise<QuickstartPublication[]> =>
                        await loadFeedPage('newsletter', values.newsletterPublications),
                },
            ],
        }
    }),
    reducers({
        enablingProducts: [
            {} as Record<string, boolean>,
            {
                enableProduct: (state, { productKey }) => ({ ...state, [productKey]: true }),
                productEnableFinished: (state, { productKey }) => {
                    const { [productKey]: _, ...rest } = state
                    return rest
                },
            },
        ],
        publicationsHasMore: [
            { blog: true, newsletter: true } as Record<PublicationFeedKey, boolean>,
            {
                setPublicationsHasMore: (state, { feed, hasMore }) => ({ ...state, [feed]: hasMore }),
            },
        ],
        setupModalProductKey: [
            null as ProductKey | null,
            {
                openToolSetupModal: (_, { productKey }) => productKey,
                closeToolSetupModal: () => null,
            },
        ],
        taskGuidanceSelection: [
            null as QuickstartTaskGuidanceSelection | null,
            {
                openTaskGuidance: (_, { productKey, stepKey }) => ({ productKey, stepKey }),
                closeTaskGuidance: () => null,
            },
        ],
        companionSetup: [
            null as QuickstartCompanionSetup | null,
            {
                openCompanionSetup: (_, { companion }) => companion,
                closeCompanionSetup: () => null,
            },
        ],
    }),
    selectors({
        hasIngestedEvent: [(s) => [s.currentTeam], (currentTeam): boolean => !!currentTeam?.ingested_event],
        products: [
            (s) => [s.currentTeam, s.activationData, s.healthIssues],
            (currentTeam, activationData, healthIssues): QuickstartProduct[] => {
                if (!isFullTeam(currentTeam)) {
                    return []
                }
                const ctx: StatusContext = {
                    team: currentTeam,
                    signals: activationData.signals ?? EMPTY_TOOL_SIGNALS,
                    resources: activationData.resources,
                    healthIssues,
                }
                return QUICKSTART_PRODUCT_ORDER.map((key) => buildProduct(key, ctx)).filter(
                    (product): product is QuickstartProduct => product !== null
                )
            },
        ],
        activeProductCount: [
            (s) => [s.products],
            (products: QuickstartProduct[]): number =>
                products.filter((product) => product.status.level === 'live').length,
        ],
        totalProductCount: [(s) => [s.products], (products: QuickstartProduct[]): number => products.length],
        setupModalProduct: [
            (s) => [s.setupModalProductKey, s.products],
            (setupModalProductKey: ProductKey | null, products: QuickstartProduct[]): QuickstartProduct | null =>
                (setupModalProductKey && products.find((product) => product.key === setupModalProductKey)) || null,
        ],
        selectedTask: [
            (s) => [s.taskGuidanceSelection, s.products],
            (
                selection: QuickstartTaskGuidanceSelection | null,
                products: QuickstartProduct[]
            ): QuickstartSelectedTask | null => {
                if (!selection) {
                    return null
                }
                const product = products.find(({ key }) => key === selection.productKey)
                const step = product?.status.journey.find(({ key }) => key === selection.stepKey)
                return product && step ? { product, step } : null
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        enableProduct: async ({ productKey }) => {
            const definition = QUICKSTART_PRODUCT_DEFINITIONS[productKey]
            if (!definition?.optInPayload) {
                actions.productEnableFinished(productKey)
                return
            }
            try {
                await teamLogic.asyncActions.updateCurrentTeam(definition.optInPayload)
            } catch (error) {
                // The opt-in didn't apply, so don't record an enable that never happened.
                // Some team fields (e.g. conversations_enabled) are admin-only.
                const status = (error as { status?: number } | null)?.status
                lemonToast.error(
                    status === 403
                        ? 'Only project admins can turn this on. Ask an admin to enable it.'
                        : "Couldn't enable it. Please try again."
                )
                return
            } finally {
                actions.productEnableFinished(productKey)
            }
            posthog.capture('quickstart product enabled', { product_key: productKey })
            void addProductIntent({
                product_type: productKey,
                intent_context: ProductIntentContext.QUICK_START_PRODUCT_SELECTED,
            })
        },
        // Fires after signals settle so the payload reflects real data, not the empty fallback
        loadActivationDataSuccess: () => {
            if (!isFullTeam(values.currentTeam)) {
                return
            }
            posthog.capture('quickstart viewed', {
                ...getQuickstartTrackingProperties(values.currentTeam, values.products),
                activation_signals_loaded: values.activationData.signals !== null,
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadActivationData()
        actions.loadHealthIssues()
        actions.loadBlogPublications()
        actions.loadNewsletterPublications()
    }),
])
