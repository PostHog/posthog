import type { Meta, StoryObj } from '@storybook/react'
import type { ReactNode } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { DashboardPlacement } from '~/types'

import { WidgetCard } from '../../components/WidgetCard/WidgetCard'
import { WidgetCardBody } from '../../components/WidgetCard/WidgetCardBody'
import { WidgetCardHeader, widgetCardShouldHideMoreButton } from '../../components/WidgetCard/WidgetCardHeader'
import {
    mockMoreOverlay,
    widgetStorybookParameters,
    widgetTileFrameDecorator,
} from '../../components/WidgetCard/widgetCardStoryFixtures'
import { surveyResultsSamplePayload } from '../../components/WidgetCard/widgetOverviewStoryFixtures'
import { getDashboardWidgetCatalogEntry, getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { useWidgetAvailability } from '../../widget_types/widgetAvailability'
import { DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON } from '../constants'
import type { DashboardWidgetComponentProps } from '../registry'
import { SurveyResultsWidget } from './SurveyResultsWidget'
import { SurveyResultsWidgetTileFilters } from './SurveyResultsWidgetTileFilters'

const SURVEY_RESULTS_CATALOG = getDashboardWidgetCatalogEntry('survey_results')!
const DEFAULT_CONFIG = SURVEY_RESULTS_CATALOG.defaultConfig as Record<string, unknown>

// The empty-state picker drives surveyPickerLogic, which fetches surveys to resolve the selected
// name — mock the list/retrieve endpoints so it renders cleanly.
const pickerSurveys = [
    { id: 'survey-101', name: 'Post-purchase feedback', archived: false, start_date: '2026-05-12T00:00:00.000Z' },
    { id: 'survey-102', name: 'NPS survey', archived: false, start_date: null },
]
const surveysApiDecorator = mswDecorator({
    get: {
        '/api/projects/:team_id/surveys/': () => [200, { results: pickerSurveys, count: pickerSurveys.length }],
        '/api/projects/:team_id/surveys/:id/': ({ params }) => [
            200,
            pickerSurveys.find((survey) => survey.id === params.id) ?? pickerSurveys[0],
        ],
    },
})

type SurveyResultsWidgetTileStoryProps = DashboardWidgetComponentProps & {
    title?: string
    description?: string
    showDescription?: boolean
    body?: ReactNode
    /** When true, tile filter bar matches view-only dashboard access (no edit permissions). */
    tileFiltersReadOnly?: boolean
}

function SurveyResultsWidgetTileStory({
    title = '',
    description = SURVEY_RESULTS_CATALOG.description,
    showDescription = true,
    body,
    tileFiltersReadOnly = false,
    ...widgetProps
}: SurveyResultsWidgetTileStoryProps): JSX.Element {
    const widgetTypeLabel = getDashboardWidgetGroupLabel(SURVEY_RESULTS_CATALOG.groupId)
    const defaultTitle = SURVEY_RESULTS_CATALOG.headerTitle ?? SURVEY_RESULTS_CATALOG.label
    const { isAvailable: showTileFilters } = useWidgetAvailability(SURVEY_RESULTS_CATALOG.availability)

    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={SURVEY_RESULTS_CATALOG.headerLayout}
                title={title}
                defaultTitle={defaultTitle}
                titleHref={SURVEY_RESULTS_CATALOG.titleHref}
                widgetTypeLabel={widgetTypeLabel}
                config={widgetProps.config}
                headerMeta={SURVEY_RESULTS_CATALOG.headerMeta}
                description={description}
                showDescription={showDescription}
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            {showTileFilters ? (
                <SurveyResultsWidgetTileFilters
                    tileId={widgetProps.tileId}
                    config={widgetProps.config}
                    onUpdateConfig={tileFiltersReadOnly ? undefined : widgetProps.onUpdateConfig}
                    disabledReason={tileFiltersReadOnly ? DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON : undefined}
                />
            ) : null}
            <WidgetCardBody>{body ?? <SurveyResultsWidget {...widgetProps} />}</WidgetCardBody>
        </WidgetCard>
    )
}

const meta: Meta<typeof SurveyResultsWidgetTileStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Surveys/Survey results',
    component: SurveyResultsWidgetTileStory,
    parameters: {
        layout: 'padded',
        ...widgetStorybookParameters,
    },
    decorators: [surveysApiDecorator, ...widgetTileFrameDecorator],
    args: {
        tileId: 1,
        config: { ...DEFAULT_CONFIG, surveyId: 'survey-101' },
        loading: false,
        result: null,
        onUpdateConfig: () => undefined,
        onRefresh: () => undefined,
    },
}

export default meta

type Story = StoryObj<typeof SurveyResultsWidgetTileStory>

export const Default: Story = {
    args: {
        title: 'Survey results',
        loading: false,
        result: surveyResultsSamplePayload,
    },
}

export const Loading: Story = {
    args: {
        title: 'Survey results',
        loading: true,
        result: null,
    },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}

export const Empty: Story = {
    args: {
        title: 'Survey results',
        loading: false,
        result: {
            ...surveyResultsSamplePayload,
            responses: [],
            hasMore: false,
        },
    },
    parameters: {
        docs: {
            description: {
                story: 'Survey selected but no responses have come in yet.',
            },
        },
    },
}

export const NotConfigured: Story = {
    args: {
        title: 'Survey results',
        config: DEFAULT_CONFIG,
        loading: false,
        result: { survey: null, responses: [], needsConfiguration: true, hasSurveys: true },
    },
    parameters: {
        docs: {
            description: {
                story: 'Prompt to pick a survey when the tile has none selected yet.',
            },
        },
    },
}

export const TileFiltersReadOnly: Story = {
    args: {
        title: 'Survey results',
        loading: false,
        result: surveyResultsSamplePayload,
        tileFiltersReadOnly: true,
    },
    parameters: {
        docs: {
            description: {
                story: 'View-only dashboard access — the survey picker shows the selection read-only.',
            },
        },
    },
}

export const SurveyNotFound: Story = {
    args: {
        title: 'Survey results',
        loading: false,
        result: { survey: null, responses: [], surveyNotFound: true },
    },
    parameters: {
        docs: {
            description: {
                story: 'The selected survey was deleted — prompt to pick another in settings.',
            },
        },
    },
}
