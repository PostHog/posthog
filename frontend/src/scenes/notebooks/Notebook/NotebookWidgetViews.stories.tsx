import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { HttpResponse } from 'msw'

import { App } from 'scenes/App'
import dashboardFixture from 'scenes/dashboard/__mocks__/dashboard.json'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { recordingPlaylists } from 'scenes/session-recordings/__mocks__/recording_playlists'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { recordings } from 'scenes/session-recordings/__mocks__/recordings'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_DRAFT from '~/mocks/fixtures/api/experiments/_experiment_draft.json'
import { NodeKind } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    ActionType,
    CohortType,
    EarlyAccessFeatureStage,
    EarlyAccessFeatureType,
    Survey,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
} from '~/types'

import traceWithoutContent from 'products/ai_observability/frontend/__mocks__/traceWithoutContent.json'
import {
    errorTrackingEventsQueryResponse,
    errorTrackingQueryResponse,
    errorTrackingTypeIssue,
} from 'products/error_tracking/frontend/__mocks__/error_tracking_query'
import { NEW_WORKFLOW } from 'products/workflows/frontend/Workflows/workflowLogic'

import { expect, waitFor } from 'storybook/test'

import featureFlags from '../../feature-flags/__mocks__/feature_flags.json'
import { notebookWidgetCatalog, NotebookWidgetTagName } from '../notebookWidgetCatalog'
import { notebookTestTemplate } from './__mocks__/notebook-template-for-snapshot'
import { buildMarkdownNotebookContent, serializeMarkdownNotebookComponent } from './markdownNotebookV2'

const FEATURE_FLAG_ID = 1779
const SURVEY_ID = '0187c279-bcae-0000-34f5-4f121921f005'
const EXPERIMENT_ID = EXPERIMENT_DRAFT.id
const EARLY_ACCESS_FEATURE_ID = '0187c22c-06d9-0000-34fe-daa2e2afb503'
const COHORT_ID = 1
const INSIGHT_ID = 'widget-insight'
const RECORDING_ID = String(recordings[0].id)
const PLAYLIST_ID = 'widget-playlist'
const PERSON_ID = '0198a76b-7d8b-7000-8fb2-a6f4d27b0811'
const GROUP_KEY = 'example-company'
const ERROR_TRACKING_ISSUE_ID = '01890a1b-2c3d-4e4f-8a9b-0c1d2e3f4a5b'
const LLM_TRACE_ID = traceWithoutContent.id
const DASHBOARD_ID = 5
const ACTION_ID = 123
const WORKFLOW_ID = 'widget-workflow'

const featureFlag = {
    ...featureFlags.results.find((flag) => flag.id === FEATURE_FLAG_ID),
    can_edit: true,
}

const survey = {
    id: SURVEY_ID,
    name: 'Onboarding feedback',
    description: 'Learn where new users need help.',
    type: SurveyType.Popover,
    created_at: '2023-04-27T10:04:37.977401Z',
    created_by: null,
    questions: [{ id: 'question-1', question: 'What could we improve?', type: SurveyQuestionType.Open }],
    conditions: null,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    targeting_flag_filters: undefined,
    appearance: { backgroundColor: 'white', submitButtonColor: '#2C2C2C' },
    start_date: '2023-04-29T10:04:37.977401Z',
    end_date: null,
    archived: false,
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
    schedule: SurveySchedule.Once,
    user_access_level: AccessControlLevel.Editor,
} as Survey

const earlyAccessFeature = {
    id: EARLY_ACCESS_FEATURE_ID,
    feature_flag: {
        id: 7,
        team_id: 1,
        key: 'guided-onboarding',
        name: 'Guided onboarding',
        active: true,
        deleted: false,
        ensure_experience_continuity: false,
        filters: { groups: [], payloads: {}, multivariate: null },
    },
    name: 'Guided onboarding',
    description: 'A guided setup flow for new workspaces.',
    stage: EarlyAccessFeatureStage.Concept,
    documentation_url: 'https://example.com/guided-onboarding',
    created_at: '2023-04-27T10:04:37.977401Z',
} as EarlyAccessFeatureType

const cohort = {
    id: COHORT_ID,
    name: 'Recently activated users',
    count: 1234,
    is_static: false,
    is_calculating: false,
    last_calculation: '2023-07-03T10:00:00Z',
    created_by: null,
    created_at: '2023-06-15T10:00:00Z',
    deleted: false,
    filters: { properties: { type: 'AND', values: [] } },
    groups: [],
} as CohortType

const insight = {
    ...dashboardFixture.tiles[0].insight,
    id: 901,
    short_id: INSIGHT_ID,
    name: 'Activation by day',
    description: 'Daily activation events for the current release.',
}

const recording = {
    ...recordingMetaJson,
    id: RECORDING_ID,
    person: {
        ...recordingMetaJson.person,
        properties: { ...recordingMetaJson.person?.properties, email: 'viewer@example.com' },
    },
}

const playlist = {
    ...recordingPlaylists.results[0],
    short_id: PLAYLIST_ID,
    name: 'New user sessions',
    description: 'Sessions from people completing their first setup.',
}

const personHogQLRow = [
    PERSON_ID,
    ['viewer@example.com'],
    JSON.stringify({
        email: 'viewer@example.com',
        name: 'Taylor Example',
        $browser: 'Chrome',
        $device_type: 'Desktop',
        $geoip_country_code: 'BE',
        $geoip_country_name: 'Belgium',
    }),
    true,
    '2023-06-15T10:00:00Z',
    '2023-07-03T10:00:00Z',
]

const group = {
    group_type_index: 0,
    group_key: GROUP_KEY,
    group_properties: { name: 'Example Company', industry: 'Software', mrr: 1200 },
    created_at: '2023-06-15T10:00:00Z',
}

const errorTrackingIssue = {
    ...errorTrackingTypeIssue,
    id: ERROR_TRACKING_ISSUE_ID,
    name: 'Checkout request failed',
    description: 'The checkout request returned an unexpected response.',
}

const errorTrackingSummary = {
    ...errorTrackingQueryResponse,
    results: [
        {
            ...errorTrackingQueryResponse.results[0],
            ...errorTrackingIssue,
            aggregations: {
                ...errorTrackingQueryResponse.results[0].aggregations,
                occurrences: 38,
                users: 8,
            },
        },
    ],
}

const errorTrackingActivityResponse = {
    columns: ['*', 'timestamp', 'person'],
    hasMore: false,
    results: errorTrackingEventsQueryResponse.results.map((row) => [
        {
            uuid: row[0] as string,
            properties: {
                ...JSON.parse(row[1] as string),
                $exception_types: ['TypeError'],
                $exception_values: ['The checkout request returned an unexpected response.'],
            },
        },
        row[2],
        row[3],
    ]),
}

const dashboard = {
    ...dashboardFixture,
    id: DASHBOARD_ID,
    name: 'Growth overview',
    description: 'The metrics used in the weekly growth review.',
    is_shared: true,
    tiles: dashboardFixture.tiles.map((tile, index) => ({ ...tile, id: index + 1 })),
}

const action = {
    id: ACTION_ID,
    name: 'Completed onboarding',
    description: 'People who completed the onboarding flow.',
    tags: ['onboarding'],
    post_to_slack: false,
    slack_message_format: '',
    steps: [
        {
            event: 'onboarding completed',
            selector: null,
            text: null,
            text_matching: null,
            href: null,
            href_matching: 'contains',
            url: null,
            url_matching: 'contains',
        },
    ],
    created_at: '2023-06-15T10:00:00Z',
    created_by: MOCK_DEFAULT_BASIC_USER,
    deleted: false,
    is_calculating: false,
    last_calculated_at: '2023-07-03T10:00:00Z',
    pinned_at: null,
    user_access_level: AccessControlLevel.Editor,
    reference_count: 1,
} as ActionType

const workflow = {
    ...NEW_WORKFLOW,
    id: WORKFLOW_ID,
    name: 'Welcome new users',
    description: 'Send onboarding guidance after signup.',
    team_id: 1,
    created_at: '2023-06-15T10:00:00Z',
    updated_at: '2023-07-03T10:00:00Z',
}

function notebookWidgetViewTestTemplate(
    tagName: NotebookWidgetTagName,
    title: string,
    id: string | number,
    attributes: Record<string, string | number> = {}
): ReturnType<typeof notebookTestTemplate> {
    const widget = notebookWidgetCatalog.widgets[tagName]
    const views = [
        { key: widget.defaultView.name, label: widget.defaultView.label, isDefault: true },
        ...Object.entries(widget.views).map(([key, view]) => ({ key, label: view.label, isDefault: false })),
    ]
    const markdown = [
        `# ${title}`,
        ...views.flatMap(({ key, label, isDefault }) => [
            `## ${label}`,
            serializeMarkdownNotebookComponent(tagName, {
                id,
                ...attributes,
                ...(isDefault ? {} : { view: key }),
            }),
        ]),
    ].join('\n\n')

    return { ...notebookTestTemplate(title, []), content: buildMarkdownNotebookContent(markdown) }
}

const notebooks = {
    'feature-flag-widget-views': notebookWidgetViewTestTemplate('FeatureFlag', 'Feature flag views', FEATURE_FLAG_ID),
    'survey-widget-views': notebookWidgetViewTestTemplate('Survey', 'Survey views', SURVEY_ID),
    'experiment-widget-views': notebookWidgetViewTestTemplate('Experiment', 'Experiment views', EXPERIMENT_ID),
    'early-access-feature-widget-views': notebookWidgetViewTestTemplate(
        'EarlyAccessFeature',
        'Early access feature views',
        EARLY_ACCESS_FEATURE_ID
    ),
    'cohort-widget-views': notebookWidgetViewTestTemplate('Cohort', 'Cohort views', COHORT_ID),
    'insight-widget-views': notebookWidgetViewTestTemplate('Insight', 'Insight views', INSIGHT_ID),
    'recording-widget-views': notebookWidgetViewTestTemplate('Recording', 'Session recording views', RECORDING_ID),
    'recording-playlist-widget-views': notebookWidgetViewTestTemplate(
        'RecordingPlaylist',
        'Recording playlist views',
        PLAYLIST_ID,
        { height: 400 }
    ),
    'person-widget-views': notebookWidgetViewTestTemplate('Person', 'Person views', PERSON_ID),
    'group-widget-views': notebookWidgetViewTestTemplate('Group', 'Group views', GROUP_KEY, { groupTypeIndex: 0 }),
    'error-tracking-issue-widget-views': notebookWidgetViewTestTemplate(
        'ErrorTrackingIssue',
        'Error tracking issue views',
        ERROR_TRACKING_ISSUE_ID
    ),
    'llm-trace-widget-views': notebookWidgetViewTestTemplate('LLMTrace', 'LLM trace views', LLM_TRACE_ID),
    'dashboard-widget-views': notebookWidgetViewTestTemplate('Dashboard', 'Dashboard views', DASHBOARD_ID),
    'action-widget-views': notebookWidgetViewTestTemplate('Action', 'Action views', ACTION_ID),
    'workflow-widget-views': notebookWidgetViewTestTemplate('Workflow', 'Workflow views', WORKFLOW_ID),
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Notebooks/Widget views',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04',
        testOptions: {
            viewport: { width: 1400, height: 4000 },
            waitForSelector: '.MarkdownNotebook__real-node-content',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/notebooks/:short_id': ({ params }) => [
                    200,
                    notebooks[params.short_id as keyof typeof notebooks],
                ],
                [`/api/projects/:team_id/feature_flags/${FEATURE_FLAG_ID}/`]: featureFlag,
                [`/api/projects/:team_id/feature_flags/${FEATURE_FLAG_ID}/status`]: {
                    status: 'active',
                    reason: 'Feature flag is active',
                },
                [`/api/projects/:team_id/surveys/${SURVEY_ID}/`]: survey,
                '/api/projects/:team_id/surveys/responses_count/': { [SURVEY_ID]: 42 },
                [`/api/projects/:team_id/experiments/${EXPERIMENT_ID}/`]: EXPERIMENT_DRAFT,
                '/api/projects/:team_id/experiment_holdouts': [],
                '/api/projects/:team_id/experiment_saved_metrics/': [],
                [`/api/projects/:team_id/early_access_feature/${EARLY_ACCESS_FEATURE_ID}/`]: earlyAccessFeature,
                [`/api/projects/:team_id/cohorts/${COHORT_ID}/`]: cohort,
                [`/api/environments/:team_id/insights/${INSIGHT_ID}/`]: insight,
                [`/api/projects/:team_id/insights/${INSIGHT_ID}/`]: insight,
                '/api/environments/:team_id/session_recordings/:id': recording,
                '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) => {
                    if (new URL(request.url).searchParams.get('source') === 'blob_v2') {
                        return new HttpResponse(snapshotsAsJSONLines())
                    }

                    return {
                        sources: [
                            {
                                source: 'blob_v2',
                                start_timestamp: '2023-08-11T12:03:36.097000Z',
                                end_timestamp: '2023-08-11T12:04:52.268000Z',
                                blob_key: '0',
                            },
                        ],
                    }
                },
                '/api/projects/:team_id/session_recording_playlists/:playlist_id': playlist,
                '/api/projects/:team_id/session_recording_playlists/:playlist_id/recordings': {
                    has_next: false,
                    results: recordings,
                    version: 1,
                },
                '/api/environments/:team_id/groups/find': group,
                '/api/environments/:team_id/error_tracking/issues/:id/': errorTrackingIssue,
                '/api/environments/:team_id/error_tracking/issues/:id/fingerprints/': [],
                '/api/environments/:team_id/error_tracking/fingerprints': { next: null, results: [] },
                '/api/environments/:team_id/error_tracking/spike_events': { results: [] },
                [`/api/environments/:team_id/dashboards/${DASHBOARD_ID}/`]: dashboard,
                '/api/environments/:team_id/insights/:insight_id/': ({ params }) =>
                    dashboardFixture.tiles.find((tile) => String(tile.insight?.id) === String(params.insight_id))
                        ?.insight || insight,
                [`/api/projects/:team_id/actions/${ACTION_ID}/`]: action,
                [`/api/environments/:team_id/actions/${ACTION_ID}/`]: action,
                [`/api/environments/:team_id/hog_flows/${WORKFLOW_ID}/`]: workflow,
                [`/api/environments/:team_id/hog_flows/${WORKFLOW_ID}/schedules/`]: [],
                [`/api/environments/:team_id/hog_flows/${WORKFLOW_ID}/batch_jobs/`]: [],
                '/api/environments/:team_id/hog_function_templates/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
                '/api/projects/:team_id/actions/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/integrations': {},
                '/api/environments/:team_id/default_evaluation_contexts/': {
                    default_evaluation_contexts: [],
                    available_contexts: [],
                    hidden_contexts: [],
                    enabled: false,
                },
                '/api/environments/:team_id/default_release_conditions/': [],
            },
            patch: {
                '/api/projects/:team_id/session_recording_playlists/:playlist_id': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    return { ...playlist, ...body }
                },
            },
            post: {
                '/api/projects/:team_id/session_recording_playlists/:playlist_id/playlist_viewed': { success: true },
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as {
                        query?: { kind?: string; query?: string; select?: string[] }
                    }
                    const query = body.query

                    if (query?.kind === NodeKind.TraceQuery) {
                        return { results: [traceWithoutContent] }
                    }
                    if (query?.kind === NodeKind.ErrorTrackingQuery) {
                        return errorTrackingSummary
                    }
                    if (query?.kind === NodeKind.EventsQuery) {
                        return query.select?.includes('*')
                            ? errorTrackingActivityResponse
                            : errorTrackingEventsQueryResponse
                    }
                    if (query?.kind === NodeKind.HogQLQuery) {
                        if (query.query?.includes('FROM persons\n')) {
                            return { results: [personHogQLRow] }
                        }
                        if (query.query?.includes('persons_revenue_analytics')) {
                            return { results: [[1200, 50000]] }
                        }
                        if (query.query?.includes('groups_revenue_analytics')) {
                            return { results: [[2400, 75000]] }
                        }
                        if (query.query?.includes('count(DISTINCT $session_id)')) {
                            return { results: [[3, 42]] }
                        }
                    }

                    return { columns: [], results: [], types: [] }
                },
                '/api/environments/:team_id/error_tracking/stack_frames/batch_get/': { results: [] },
                '/api/projects/:team_id/feature_flags/user_blast_radius/': { affected: 120, total: 2000 },
            },
        }),
    ],
}

export default meta

type Story = StoryObj<{}>

export const FeatureFlagViews: Story = { parameters: { pageUrl: urls.notebook('feature-flag-widget-views') } }
export const SurveyViews: Story = { parameters: { pageUrl: urls.notebook('survey-widget-views') } }
export const ExperimentViews: Story = { parameters: { pageUrl: urls.notebook('experiment-widget-views') } }
export const EarlyAccessFeatureViews: Story = {
    parameters: { pageUrl: urls.notebook('early-access-feature-widget-views') },
}
export const CohortViews: Story = { parameters: { pageUrl: urls.notebook('cohort-widget-views') } }
export const InsightViews: Story = {
    parameters: { pageUrl: urls.notebook('insight-widget-views') },
    play: async ({ canvasElement }) => {
        await waitFor(() => {
            expect(
                canvasElement.querySelectorAll('.MarkdownNotebook__real-node-content').length
            ).toBeGreaterThanOrEqual(4)
            expect(
                canvasElement.querySelectorAll('.MarkdownNotebook__component-toolbar-title-placeholder')
            ).toHaveLength(0)
        })
    },
}
export const RecordingViews: Story = {
    parameters: {
        pageUrl: urls.notebook('recording-widget-views'),
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export const RecordingPlaylistViews: Story = {
    parameters: {
        pageUrl: urls.notebook('recording-playlist-widget-views'),
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: '.MarkdownNotebook__component-toolbar-title[title="New user sessions"]',
        },
    },
}
export const PersonViews: Story = { parameters: { pageUrl: urls.notebook('person-widget-views') } }
export const GroupViews: Story = { parameters: { pageUrl: urls.notebook('group-widget-views') } }
export const ErrorTrackingIssueViews: Story = {
    parameters: { pageUrl: urls.notebook('error-tracking-issue-widget-views') },
}
export const LLMTraceViews: Story = { parameters: { pageUrl: urls.notebook('llm-trace-widget-views') } }
export const DashboardViews: Story = { parameters: { pageUrl: urls.notebook('dashboard-widget-views') } }
export const ActionViews: Story = { parameters: { pageUrl: urls.notebook('action-widget-views') } }
export const WorkflowViews: Story = {
    parameters: { pageUrl: urls.notebook('workflow-widget-views') },
    play: async ({ canvasElement }) => {
        await waitFor(
            () => {
                const editor = canvasElement.querySelector<HTMLElement>('[data-attr="workflow-editor"]')
                const canvas = editor?.querySelector<HTMLElement>('.react-flow')
                const nodes = Array.from(editor?.querySelectorAll<HTMLElement>('.react-flow__node') || [])

                expect(canvas).not.toBeNull()
                expect(nodes).toHaveLength(2)

                const canvasBounds = canvas!.getBoundingClientRect()
                expect(
                    nodes.every((node) => {
                        const nodeBounds = node.getBoundingClientRect()
                        return nodeBounds.top >= canvasBounds.top && nodeBounds.bottom <= canvasBounds.bottom
                    })
                ).toBe(true)
            },
            { timeout: 10000 }
        )
    },
}
