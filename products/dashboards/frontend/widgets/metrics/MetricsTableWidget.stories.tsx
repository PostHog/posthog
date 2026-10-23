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
import { MetricsTableWidget } from './MetricsTableWidget'
import { metricsTableWidgetSampleResult } from './metricsTableWidgetSampleData'

const CATALOG = getDashboardWidgetCatalogEntry('metrics_table')
const CONFIGURED = { ...(CATALOG.defaultConfig as Record<string, unknown>), groupBy: 'http.route' }

function StoryTile(props: DashboardWidgetComponentProps): JSX.Element {
    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={CATALOG.headerLayout}
                title=""
                defaultTitle={CATALOG.headerTitle ?? CATALOG.label}
                titleHref={CATALOG.titleHref}
                widgetTypeLabel={getDashboardWidgetGroupLabel(CATALOG.groupId)}
                config={props.config}
                headerMeta={CATALOG.headerMeta}
                description={CATALOG.description}
                showDescription
                loading={props.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            <WidgetCardBody>
                <MetricsTableWidget {...props} />
            </WidgetCardBody>
        </WidgetCard>
    )
}

const meta: Meta<typeof StoryTile> = {
    title: 'Products/Dashboards/Dashboard Widgets/Widget types/Metrics/Metrics table',
    component: StoryTile,
    parameters: { layout: 'padded', ...widgetStorybookParameters },
    decorators: [...widgetTileFrameDecorator],
    args: {
        tileId: 1,
        config: CONFIGURED,
        loading: false,
        result: metricsTableWidgetSampleResult,
        onRefresh: () => undefined,
    },
}
export default meta
type Story = StoryObj<typeof StoryTile>

export const Populated: Story = {}

export const Loading: Story = {
    args: { loading: true, result: null },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}

export const Empty: Story = {
    args: { result: { ...metricsTableWidgetSampleResult, rows: [], totalCount: 0, hasMore: false } },
}

export const NeedsConfiguration: Story = {
    args: { config: CATALOG.defaultConfig as Record<string, unknown>, result: { needsConfiguration: true, rows: [] } },
}
