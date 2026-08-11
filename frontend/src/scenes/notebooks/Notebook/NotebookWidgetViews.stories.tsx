import { Meta, StoryObj } from '@storybook/react'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_DRAFT from '~/mocks/fixtures/api/experiments/_experiment_draft.json'
import {
    AccessControlLevel,
    CohortType,
    EarlyAccessFeatureStage,
    EarlyAccessFeatureType,
    Survey,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
} from '~/types'

import featureFlags from '../../feature-flags/__mocks__/feature_flags.json'
import { notebookWidgetCatalog, NotebookWidgetTagName } from '../notebookWidgetCatalog'
import { NotebookNodeType } from '../types'
import { notebookTestTemplate } from './__mocks__/notebook-template-for-snapshot'

const FEATURE_FLAG_ID = 1779
const SURVEY_ID = '0187c279-bcae-0000-34f5-4f121921f005'
const EXPERIMENT_ID = EXPERIMENT_DRAFT.id
const EARLY_ACCESS_FEATURE_ID = '0187c22c-06d9-0000-34fe-daa2e2afb503'
const COHORT_ID = 1

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

function createWidgetViewNodes(
    tagName: NotebookWidgetTagName,
    nodeType: NotebookNodeType,
    id: string | number
): JSONContent[] {
    const widget = notebookWidgetCatalog.widgets[tagName]
    const views = [
        { key: widget.defaultView.name, label: widget.defaultView.label, isDefault: true },
        ...Object.entries(widget.views).map(([key, view]) => ({ key, label: view.label, isDefault: false })),
    ]

    return views.flatMap(({ key, label, isDefault }, index) => [
        {
            type: 'heading',
            attrs: { level: 2 },
            content: [{ type: 'text', text: label }],
        },
        {
            type: nodeType,
            attrs: {
                id,
                nodeId: `${tagName}-${key}-${index}`,
                ...(isDefault ? {} : { view: key }),
            },
        },
    ])
}

const notebooks = {
    'feature-flag-widget-views': notebookTestTemplate(
        'Feature flag views',
        createWidgetViewNodes('FeatureFlag', NotebookNodeType.FeatureFlag, FEATURE_FLAG_ID)
    ),
    'survey-widget-views': notebookTestTemplate(
        'Survey views',
        createWidgetViewNodes('Survey', NotebookNodeType.Survey, SURVEY_ID)
    ),
    'experiment-widget-views': notebookTestTemplate(
        'Experiment views',
        createWidgetViewNodes('Experiment', NotebookNodeType.Experiment, EXPERIMENT_ID)
    ),
    'early-access-feature-widget-views': notebookTestTemplate(
        'Early access feature views',
        createWidgetViewNodes('EarlyAccessFeature', NotebookNodeType.EarlyAccessFeature, EARLY_ACCESS_FEATURE_ID)
    ),
    'cohort-widget-views': notebookTestTemplate(
        'Cohort views',
        createWidgetViewNodes('Cohort', NotebookNodeType.Cohort, COHORT_ID)
    ),
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
            post: {
                '/api/environments/:team_id/query/:kind': {
                    columns: [],
                    results: [],
                    types: [],
                },
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
