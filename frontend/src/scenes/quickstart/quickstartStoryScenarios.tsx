import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

// Shared scaffolding for the Quickstart scene stories. Not a *.stories.* file on purpose:
// Storybook must not pick it up as a stories module.
import { useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { activeCloudRunLogic } from 'scenes/onboarding/shared/wizard-sync/activeCloudRunLogic'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

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

const sseEvent = (data: object): string => `data: ${JSON.stringify(data)}\n\n`
const sseStep = (group: string, step: string, status: string, label: string, detail: string | null = null): string =>
    sseEvent({
        type: 'notification',
        notification: { method: '_posthog/progress', params: { group, step, status, label, detail } },
    })

const TASK_RUN_STREAM_BODY = [
    sseEvent({
        type: 'task_run_state',
        status: 'in_progress',
        stage: 'work',
        output: null,
        branch: null,
        error_message: null,
        updated_at: '2026-07-15T12:00:00Z',
        completed_at: null,
    }),
    sseStep('setup', 'sandbox', 'completed', 'Set up sandbox'),
    sseStep('setup', 'clone', 'completed', 'Cloned repository'),
    sseStep('setup', 'wizard', 'in_progress', 'Running setup wizard', 'Installing the PostHog SDK'),
    sseStep('deliver', 'pr', 'pending', 'Opening pull request'),
    'event: stream-end\ndata: {}\n\n',
].join('')

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

export interface ScenarioResources {
    hasLogs?: boolean
    sources?: number
    workflows?: number
    eventTriggeredWorkflows?: number
    symbolSets?: number
    errorAlerts?: number
    tickets?: number
}

/** One place to shape every data source the scene reads, so each story is a plain scenario.
 *
 * Pass `installation` for pre-install stories: useInstallationComplete polls loadCurrentTeam
 * every 2s, so the team endpoints must serve the story's installation state — an imperative
 * decorator alone gets overwritten by the first poll. */
export const scenarioMocks = (
    signals: Partial<QuickstartToolSignals>,
    resources: ScenarioResources = {},
    installation: InstallationState = 'complete'
): Mocks => {
    const installationComplete = installation === 'complete'
    const mockTeam = {
        ...MOCK_DEFAULT_TEAM,
        completed_snippet_onboarding: installationComplete,
        ingested_event: installationComplete,
        has_completed_onboarding_for: installationComplete ? { product_analytics: true } : {},
    }
    return {
        get: {
            '/api/environments/@current/': mockTeam,
            '/api/projects/@current/': mockTeam,
            '/api/environments/:team_id/': mockTeam,
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
            '/api/projects/:project_id/tasks/:task_id/runs/:run_id/stream': () =>
                new Response(TASK_RUN_STREAM_BODY, {
                    status: 200,
                    headers: { 'Content-Type': 'text/event-stream' },
                }),
            '/api/projects/:project_id/wizard/sessions/stream': () => [404],
            'https://posthog.com/rss.xml': () =>
                new Response(BLOG_RSS, { status: 200, headers: { 'Content-Type': 'application/rss+xml' } }),
        },
        post: {
            // Serves both the signals aggregate and the replay count: the replay loader
            // reads the first column, so keep totalEvents as a plausible recordings number
            '/api/environments/:team_id/query': { results: [signalsRow(signals)] },
        },
        patch: {
            // Every route whose response body is a team must agree with the story's installation
            // state — the default handlers answer with an installed MOCK_DEFAULT_TEAM, and a single
            // stray team payload (e.g. the scene's team PATCH) flips useInstallationComplete
            '/api/environments/:team_id/': mockTeam,
            '/api/environments/:team_id/add_product_intent/': mockTeam,
        },
    }
}

/** The "team mid-journey" scenario shared by both variants' base stories */
export const richScenarioDecorators = [
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
]

// The activation data cache is keyed by team id, which every story shares — drop it
// between stories so each scenario's mocks actually load
export const CacheBuster = (Story: React.ComponentType): JSX.Element => {
    clearQuickstartActivationCache()
    return <Story />
}

export type InstallationState = 'complete' | 'not_started' | 'running'

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

export const installationStateDecorator =
    (state: InstallationState) =>
    (Story: React.ComponentType): JSX.Element => (
        <QuickstartInstallationState state={state}>
            <Story />
        </QuickstartInstallationState>
    )
