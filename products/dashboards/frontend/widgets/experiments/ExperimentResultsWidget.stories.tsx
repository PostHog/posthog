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
import {
    experimentResultsSamplePayload,
    experimentsSampleListRows,
} from '../../components/WidgetCard/widgetOverviewStoryFixtures'
import { getDashboardWidgetCatalogEntry, getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { useWidgetAvailability } from '../../widget_types/widgetAvailability'
import { DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON } from '../constants'
import type { DashboardWidgetComponentProps } from '../registry'
import { ExperimentResultsWidget } from './ExperimentResultsWidget'
import { ExperimentResultsWidgetTileFilters } from './ExperimentResultsWidgetTileFilters'

const EXPERIMENT_RESULTS_CATALOG = getDashboardWidgetCatalogEntry('experiment_results')!
const DEFAULT_CONFIG = EXPERIMENT_RESULTS_CATALOG.defaultConfig as Record<string, unknown>

// The results tile filter (and its read-only value) drives experimentPickerLogic, which fetches
// experiments to resolve the selected name — mock the list/retrieve endpoints so it renders cleanly.
const pickerExperiments = experimentsSampleListRows.map(({ id, name, created_by }) => ({ id, name, created_by }))
const experimentsApiDecorator = mswDecorator({
    get: {
        '/api/projects/:team_id/experiments/': () => [
            200,
            { results: pickerExperiments, count: pickerExperiments.length },
        ],
        '/api/projects/:team_id/experiments/:id/': ({ params }) => {
            const id = Number(params.id)
            return [200, pickerExperiments.find((experiment) => experiment.id === id) ?? pickerExperiments[0]]
        },
    },
})

type ExperimentResultsWidgetTileStoryProps = DashboardWidgetComponentProps & {
    title?: string
    description?: string
    showDescription?: boolean
    body?: ReactNode
    /** When true, tile filter bar matches view-only dashboard access (no edit permissions). */
    tileFiltersReadOnly?: boolean
}

function ExperimentResultsWidgetTileStory({
    title = '',
    description = EXPERIMENT_RESULTS_CATALOG.description,
    showDescription = true,
    body,
    tileFiltersReadOnly = false,
    ...widgetProps
}: ExperimentResultsWidgetTileStoryProps): JSX.Element {
    const widgetTypeLabel = getDashboardWidgetGroupLabel(EXPERIMENT_RESULTS_CATALOG.groupId)
    const defaultTitle = EXPERIMENT_RESULTS_CATALOG.headerTitle ?? EXPERIMENT_RESULTS_CATALOG.label
    const { isAvailable: showTileFilters } = useWidgetAvailability(EXPERIMENT_RESULTS_CATALOG.availability)

    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={EXPERIMENT_RESULTS_CATALOG.headerLayout}
                title={title}
                defaultTitle={defaultTitle}
                titleHref={EXPERIMENT_RESULTS_CATALOG.titleHref}
                widgetTypeLabel={widgetTypeLabel}
                config={widgetProps.config}
                headerMeta={EXPERIMENT_RESULTS_CATALOG.headerMeta}
                description={description}
                showDescription={showDescription}
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            {showTileFilters ? (
                <ExperimentResultsWidgetTileFilters
                    tileId={widgetProps.tileId}
                    config={widgetProps.config}
                    onUpdateConfig={tileFiltersReadOnly ? undefined : widgetProps.onUpdateConfig}
                    disabledReason={tileFiltersReadOnly ? DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON : undefined}
                />
            ) : null}
            <WidgetCardBody>{body ?? <ExperimentResultsWidget {...widgetProps} />}</WidgetCardBody>
        </WidgetCard>
    )
}

// Storybook CSF requires a string literal `title` derived from catalog groupLabel/label.
const meta: Meta<typeof ExperimentResultsWidgetTileStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Experiments/Experiment results',
    component: ExperimentResultsWidgetTileStory,
    parameters: {
        layout: 'padded',
        ...widgetStorybookParameters,
    },
    decorators: [experimentsApiDecorator, ...widgetTileFrameDecorator],
    args: {
        tileId: 1,
        config: { ...DEFAULT_CONFIG, experimentId: 101 },
        loading: false,
        result: null,
        onUpdateConfig: () => undefined,
        onRefresh: () => undefined,
    },
}

export default meta

type Story = StoryObj<typeof ExperimentResultsWidgetTileStory>

export const Default: Story = {
    args: {
        title: 'Experiment results',
        loading: false,
        result: experimentResultsSamplePayload,
    },
}

export const TileFiltersReadOnly: Story = {
    args: {
        title: 'Experiment results',
        tileFiltersReadOnly: true,
        loading: false,
        result: experimentResultsSamplePayload,
    },
    parameters: {
        docs: {
            description: {
                story: 'Tile filter bar when the viewer lacks dashboard edit access — the selected experiment is shown as a read-only value.',
            },
        },
    },
}

export const Loading: Story = {
    args: {
        title: 'Experiment results',
        loading: true,
        result: null,
    },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}

export const NotConfigured: Story = {
    args: {
        title: 'Experiment results',
        config: DEFAULT_CONFIG,
        loading: false,
        result: { experiment: null, metrics: [], needsConfiguration: true, hasExperiments: true },
    },
    parameters: {
        docs: {
            description: {
                story: 'Prompt to pick an experiment when the tile has none selected yet.',
            },
        },
    },
}
