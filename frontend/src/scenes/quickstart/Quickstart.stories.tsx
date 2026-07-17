import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { activeCloudRunLogic } from 'scenes/onboarding/shared/wizard-sync/activeCloudRunLogic'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { Mocks } from '~/mocks/utils'
import type { TeamType } from '~/types'

import { QuickstartToolSignals, clearQuickstartActivationCache } from './quickstartLogic'

// Deterministic stand-in for the posthog.com blog feed the publications rail streams
const BLOG_RSS = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
    <channel>
        <title>PostHog blog</title>
        <item>
            <title>How we built the quickstart page</title>
            <link>https://posthog.com/blog/quickstart-page</link>
            <description>Every tool on one screen, powered by the same events.</description>
            <pubDate>Mon, 13 Jul 2026 10:00:00 GMT</pubDate>
            <dc:creator>Max Hedgehog</dc:creator>
        </item>
        <item>
            <title>Session replay, now with hogs</title>
            <link>https://posthog.com/blog/replay-hogs</link>
            <description>Watch real users navigate your app, narrated by hedgehogs.</description>
            <pubDate>Thu, 09 Jul 2026 10:00:00 GMT</pubDate>
            <dc:creator>Max Hedgehog</dc:creator>
        </item>
        <item>
            <title>Feature flags without the foot-guns</title>
            <link>https://posthog.com/blog/safe-flags</link>
            <description>Roll out changes to the right users, safely.</description>
            <pubDate>Wed, 01 Jul 2026 10:00:00 GMT</pubDate>
            <dc:creator>Max Hedgehog</dc:creator>
        </item>
    </channel>
</rss>`

/** Column order of the tool-signals HogQL aggregate in quickstartLogic's loadActivationData */
const signalsRow = (signals: Partial<QuickstartToolSignals>): number[] => [
    signals.totalEvents ?? 0,
    signals.prodEvents ?? 0,
    signals.customEvents ?? 0,
    signals.distinctCustomEvents ?? 0,
    signals.identifyCalls ?? 0,
    signals.exceptions ?? 0,
    signals.serverExceptions ?? 0,
    signals.backendEvents ?? 0,
    signals.flagCalls ?? 0,
    signals.prodFlagCalls ?? 0,
    signals.pageviews ?? 0,
    signals.prodPageviews ?? 0,
    signals.surveyResponses ?? 0,
    signals.aiGenerations ?? 0,
    signals.aiTraceEvents ?? 0,
    signals.mcpInitialize ?? 0,
    signals.mcpToolCalls ?? 0,
]

interface ScenarioResources {
    hasLogs?: boolean
    sources?: number
    workflows?: number
    eventTriggeredWorkflows?: number
    symbolSets?: number
    errorAlerts?: number
    tickets?: number
}

/** One place to shape every data source the scene reads, so each story is a plain scenario */
const scenarioMocks = (signals: Partial<QuickstartToolSignals>, resources: ScenarioResources = {}): Mocks => ({
    get: {
        '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
        '/api/billing/': billingJson,
        // liveEventsHostOrigin() points at the Storybook origin, so the live users chip gets a count
        '/stats': { users_on_product: 342 },
        '/api/environments/:team_id/logs/has_logs': { hasLogs: resources.hasLogs ?? false },
        '/api/environments/:team_id/external_data_sources/': {
            results: Array.from({ length: resources.sources ?? 0 }, (_, index) => ({ id: String(index) })),
        },
        '/api/environments/:team_id/hog_flows/': {
            results: Array.from({ length: resources.workflows ?? 0 }, (_, index) => ({
                id: String(index),
                status: 'active',
                trigger: { type: index < (resources.eventTriggeredWorkflows ?? 0) ? 'event' : 'manual' },
            })),
        },
        '/api/environments/:team_id/error_tracking/symbol_sets/': { count: resources.symbolSets ?? 0, results: [] },
        '/api/environments/:team_id/hog_functions/': { count: resources.errorAlerts ?? 0, results: [] },
        '/api/projects/:team_id/conversations/tickets/': { count: resources.tickets ?? 0, results: [] },
        '/api/projects/:projectId/wizard/sessions/latest/': () => [204, ''],
        'https://posthog.com/rss.xml': () =>
            new Response(BLOG_RSS, { status: 200, headers: { 'Content-Type': 'application/rss+xml' } }),
    },
    post: {
        // Serves both the signals aggregate and the replay count: the replay loader
        // reads the first column, so keep totalEvents as a plausible recordings number
        '/api/environments/:team_id/query': { results: [signalsRow(signals)] },
    },
})

// The activation data cache is keyed by team id, which every story shares — drop it
// between stories so each scenario's mocks actually load
const CacheBuster = (Story: React.ComponentType): JSX.Element => {
    clearQuickstartActivationCache()
    return <Story />
}

type InstallationState = 'complete' | 'not_started' | 'running'

function QuickstartInstallationState({
    state,
    children,
}: {
    state: InstallationState
    children: React.ReactNode
}): JSX.Element {
    useMountedLogic(teamLogic)
    useMountedLogic(activeCloudRunLogic)
    useMountedLogic(wizardActiveSessionDetectorLogic)

    useEffect(() => {
        const currentTeam = teamLogic.values.currentTeam
        if (!currentTeam) {
            return
        }
        const installationComplete = state === 'complete'
        teamLogic.actions.loadCurrentTeamSuccess({
            ...currentTeam,
            completed_snippet_onboarding: installationComplete,
            has_completed_onboarding_for: installationComplete ? { product_analytics: true } : {},
            ingested_event: installationComplete,
        } as TeamType)
        activeCloudRunLogic.actions.clearActiveCloudRun()
        activeCloudRunLogic.actions.setPanelMounted(false)
        wizardActiveSessionDetectorLogic.actions.markInactive()

        if (state === 'running') {
            activeCloudRunLogic.actions.setActiveCloudRun(
                'storybook-task',
                'storybook-run',
                new Date(Date.now() - 90_000).toISOString(),
                projectLogic.values.currentProjectId ?? currentTeam.id
            )
            activeCloudRunLogic.actions.setPanelMounted(true)
        }

        return () => {
            teamLogic.actions.loadCurrentTeamSuccess(currentTeam)
            activeCloudRunLogic.actions.clearActiveCloudRun()
            activeCloudRunLogic.actions.setPanelMounted(false)
            wizardActiveSessionDetectorLogic.actions.markInactive()
        }
    }, [state])

    return <>{children}</>
}

const installationStateDecorator =
    (state: InstallationState) =>
    (Story: React.ComponentType): JSX.Element => (
        <QuickstartInstallationState state={state}>
            <Story />
        </QuickstartInstallationState>
    )

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Quickstart',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-15',
        pageUrl: urls.quickstart(),
        // The scene only renders for the test variant of the experiment flag
        featureFlags: {
            [FEATURE_FLAGS.QUICKSTART_HOMEPAGE]: 'test',
            [FEATURE_FLAGS.ONBOARDING_WIZARD_SYNC]: 'test',
        },
    },
    // External artwork (Substack covers) makes pixel snapshots nondeterministic
    tags: ['test-skip'],
    decorators: [CacheBuster],
}
export default meta

type Story = StoryObj<{}>

/** A team mid-journey: several tools live, several waiting, quality partially climbed */
export const Base: Story = {
    decorators: [
        mswDecorator(
            scenarioMocks(
                {
                    totalEvents: 54210,
                    prodEvents: 32480,
                    customEvents: 1800,
                    distinctCustomEvents: 8,
                    identifyCalls: 900,
                    exceptions: 42,
                    serverExceptions: 3,
                    backendEvents: 5400,
                    flagCalls: 1200,
                    prodFlagCalls: 800,
                    pageviews: 27904,
                    prodPageviews: 21000,
                    surveyResponses: 12,
                },
                { sources: 2, workflows: 1, eventTriggeredWorkflows: 1, symbolSets: 1, tickets: 12 }
            )
        ),
    ],
}

/** Nothing has sent data in the window: every event-based tool decays back to ready/needs setup */
export const QuietProject: Story = {
    decorators: [mswDecorator(scenarioMocks({}))],
}

/** Fresh account without a wizard run: the header links back to the onboarding installation step. */
export const InstallationNotStarted: Story = {
    decorators: [installationStateDecorator('not_started'), mswDecorator(scenarioMocks({}))],
}

/** Fresh account with a wizard run: progress moves into the header and the global FAB stays hidden. */
export const InstallationRunning: Story = {
    decorators: [installationStateDecorator('running'), mswDecorator(scenarioMocks({}))],
}

/** Installed project without a wizard run: no installation CTA is shown in the header. */
export const InstallationComplete: Story = {
    decorators: [installationStateDecorator('complete'), mswDecorator(scenarioMocks({ totalEvents: 120 }))],
}

/** Everything wired: all tools live with deep quality — the "topped out" look */
export const EverythingLive: Story = {
    decorators: [
        mswDecorator(
            scenarioMocks(
                {
                    totalEvents: 812000,
                    prodEvents: 640000,
                    customEvents: 90000,
                    distinctCustomEvents: 42,
                    identifyCalls: 51000,
                    exceptions: 3100,
                    serverExceptions: 1200,
                    backendEvents: 210000,
                    flagCalls: 88000,
                    prodFlagCalls: 61000,
                    pageviews: 402000,
                    prodPageviews: 350000,
                    surveyResponses: 640,
                    aiGenerations: 12000,
                    aiTraceEvents: 4000,
                    mcpInitialize: 90,
                    mcpToolCalls: 4200,
                },
                {
                    hasLogs: true,
                    sources: 3,
                    workflows: 4,
                    eventTriggeredWorkflows: 2,
                    symbolSets: 5,
                    errorAlerts: 2,
                    tickets: 230,
                }
            )
        ),
    ],
}
