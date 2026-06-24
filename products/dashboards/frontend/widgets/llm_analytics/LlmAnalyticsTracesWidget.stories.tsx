import type { Meta, StoryObj } from '@storybook/react'
import type { ReactNode } from 'react'

import { DashboardPlacement } from '~/types'

import { WidgetCard } from '../../components/WidgetCard/WidgetCard'
import { WidgetCardBody } from '../../components/WidgetCard/WidgetCardBody'
import { WidgetCardHeader, widgetCardShouldHideMoreButton } from '../../components/WidgetCard/WidgetCardHeader'
import {
    mockMoreOverlay,
    widgetStorybookParameters,
    widgetTileFrameDecorator,
} from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry, getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON } from '../constants'
import type { DashboardWidgetComponentProps } from '../registry'
import { llmAnalyticsTracesSampleTraces } from './llmAnalyticsTracesSampleData'
import { LlmAnalyticsTracesWidget } from './LlmAnalyticsTracesWidget'
import { LlmAnalyticsTracesWidgetTileFilters } from './LlmAnalyticsTracesWidgetTileFilters'

const LLM_ANALYTICS_TRACES_CATALOG = getDashboardWidgetCatalogEntry('llm_analytics_traces')!
const DEFAULT_CONFIG = LLM_ANALYTICS_TRACES_CATALOG.defaultConfig as Record<string, unknown>

type LlmAnalyticsTracesWidgetTileStoryProps = DashboardWidgetComponentProps & {
    title?: string
    description?: string
    showDescription?: boolean
    body?: ReactNode
    filterBar?: ReactNode
    /** When true, tile filter bar matches view-only dashboard access (no edit permissions). */
    tileFiltersReadOnly?: boolean
}

function LlmAnalyticsTracesWidgetTileStory({
    title = '',
    description = 'Recent LLM traces, as on AI observability > Traces.',
    showDescription = true,
    body,
    filterBar,
    tileFiltersReadOnly = false,
    ...widgetProps
}: LlmAnalyticsTracesWidgetTileStoryProps): JSX.Element {
    const widgetTypeLabel = getDashboardWidgetGroupLabel(LLM_ANALYTICS_TRACES_CATALOG.groupId)
    const defaultTitle = LLM_ANALYTICS_TRACES_CATALOG.headerTitle ?? LLM_ANALYTICS_TRACES_CATALOG.label

    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={LLM_ANALYTICS_TRACES_CATALOG.headerLayout}
                title={title}
                defaultTitle={defaultTitle}
                titleHref={LLM_ANALYTICS_TRACES_CATALOG.titleHref}
                widgetTypeLabel={widgetTypeLabel}
                config={widgetProps.config}
                headerMeta={LLM_ANALYTICS_TRACES_CATALOG.headerMeta}
                description={description}
                showDescription={showDescription}
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            {filterBar ?? (
                <LlmAnalyticsTracesWidgetTileFilters
                    tileId={widgetProps.tileId ?? 1}
                    config={widgetProps.config}
                    onUpdateConfig={tileFiltersReadOnly ? undefined : widgetProps.onUpdateConfig}
                    disabledReason={tileFiltersReadOnly ? DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON : undefined}
                />
            )}
            <WidgetCardBody>{body ?? <LlmAnalyticsTracesWidget {...widgetProps} />}</WidgetCardBody>
        </WidgetCard>
    )
}

const meta: Meta<typeof LlmAnalyticsTracesWidgetTileStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/AI observability/Recent traces',
    component: LlmAnalyticsTracesWidgetTileStory,
    parameters: {
        layout: 'padded',
        ...widgetStorybookParameters,
    },
    decorators: [...widgetTileFrameDecorator],
    args: {
        tileId: 1,
        config: DEFAULT_CONFIG,
        loading: false,
        result: null,
        onUpdateConfig: () => undefined,
        onRefresh: () => undefined,
    },
}

export default meta

type Story = StoryObj<typeof LlmAnalyticsTracesWidgetTileStory>

export const Default: Story = {
    args: {
        title: 'Recent traces',
        config: DEFAULT_CONFIG,
        loading: false,
        result: {
            results: llmAnalyticsTracesSampleTraces,
            hasMore: true,
            limit: 10,
            totalCount: 25,
            totalCountCapped: true,
        },
    },
}

export const TileFiltersReadOnly: Story = {
    args: {
        title: 'Recent traces',
        config: { ...DEFAULT_CONFIG, dateRange: { date_from: '-7d' } },
        tileFiltersReadOnly: true,
        loading: false,
        result: {
            results: llmAnalyticsTracesSampleTraces,
            hasMore: true,
            limit: 10,
            totalCount: 25,
            totalCountCapped: true,
        },
    },
    parameters: {
        docs: {
            description: {
                story: 'Tile filter bar when the viewer lacks dashboard edit access — the date range select is disabled.',
            },
        },
    },
}

export const Loading: Story = {
    args: {
        title: 'Recent traces',
        config: DEFAULT_CONFIG,
        loading: true,
        result: null,
    },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}

export const Empty: Story = {
    args: {
        title: 'Recent traces',
        config: DEFAULT_CONFIG,
        loading: false,
        result: { results: [] },
    },
}
