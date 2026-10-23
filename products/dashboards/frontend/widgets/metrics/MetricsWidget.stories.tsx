import type { Meta, StoryObj } from '@storybook/react'

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
import type { DashboardWidgetComponentProps } from '../registry'
import { MetricsWidget } from './MetricsWidget'
import { metricsWidgetDefaultConfig, metricsWidgetDefaultTitle } from './metricsWidgetConfig'
import { metricsWidgetSampleQuery, metricsWidgetSampleResponse } from './metricsWidgetSampleData'

const METRICS_CATALOG = getDashboardWidgetCatalogEntry('metrics')

type MetricsWidgetTileStoryProps = DashboardWidgetComponentProps & {
    title?: string
}

function MetricsWidgetTileStory({ title = '', ...widgetProps }: MetricsWidgetTileStoryProps): JSX.Element {
    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={METRICS_CATALOG.headerLayout}
                title={title}
                defaultTitle={metricsWidgetDefaultTitle(widgetProps.config) ?? METRICS_CATALOG.label}
                titleHref={METRICS_CATALOG.titleHref}
                widgetTypeLabel={getDashboardWidgetGroupLabel(METRICS_CATALOG.groupId)}
                config={widgetProps.config}
                headerMeta={METRICS_CATALOG.headerMeta}
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            <WidgetCardBody error={widgetProps.error} onRefresh={widgetProps.onRefresh}>
                <MetricsWidget {...widgetProps} />
            </WidgetCardBody>
        </WidgetCard>
    )
}

// Storybook CSF requires a string literal `title` derived from catalog groupLabel/label.
const meta: Meta<typeof MetricsWidgetTileStory> = {
    title: 'Products/Dashboards/Dashboard Widgets/Widget types/Metrics/Metric',
    component: MetricsWidgetTileStory,
    parameters: {
        layout: 'padded',
        ...widgetStorybookParameters,
    },
    decorators: [...widgetTileFrameDecorator],
    args: {
        tileId: 1,
        loading: false,
        onRefresh: () => undefined,
        onEdit: () => undefined,
    },
}

export default meta

type Story = StoryObj<typeof MetricsWidgetTileStory>

export const TimeSeries: Story = {
    args: {
        config: { query: metricsWidgetSampleQuery('time_series') },
        result: metricsWidgetSampleResponse('time_series'),
    },
}

export const SingleStat: Story = {
    args: {
        config: { query: metricsWidgetSampleQuery('stat') },
        result: metricsWidgetSampleResponse('stat'),
    },
}

export const Table: Story = {
    args: {
        config: { query: metricsWidgetSampleQuery('table') },
        result: metricsWidgetSampleResponse('table'),
    },
}

export const Heatmap: Story = {
    args: {
        config: { query: metricsWidgetSampleQuery('heatmap') },
        result: metricsWidgetSampleResponse('heatmap'),
    },
}

export const NeedsConfiguration: Story = {
    args: {
        config: metricsWidgetDefaultConfig('stat'),
        result: { needsConfiguration: true },
    },
}

export const Loading: Story = {
    args: {
        config: { query: metricsWidgetSampleQuery('time_series') },
        result: null,
        loading: true,
    },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}

export const Empty: Story = {
    args: {
        config: { query: metricsWidgetSampleQuery('time_series') },
        result: { results: [] },
    },
}

export const QueryError: Story = {
    args: {
        config: { query: metricsWidgetSampleQuery('heatmap') },
        result: null,
        error: 'A heatmap needs a histogram metric.',
    },
}
