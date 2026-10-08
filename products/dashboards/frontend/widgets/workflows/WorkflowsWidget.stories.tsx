import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { DashboardPlacement } from '~/types'

import { WidgetCard } from '../../components/WidgetCard/WidgetCard'
import { WidgetCardBody } from '../../components/WidgetCard/WidgetCardBody'
import { WidgetCardHeader, widgetCardShouldHideMoreButton } from '../../components/WidgetCard/WidgetCardHeader'
import {
    mockMoreOverlay,
    widgetStorybookParameters,
    widgetTileFrameDecorator,
} from '../../components/WidgetCard/widgetCardStoryFixtures'
import { workflowsSampleRows } from '../../components/WidgetCard/widgetOverviewStoryFixtures'
import { getDashboardWidgetCatalogEntry, getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON } from '../constants'
import type { DashboardWidgetComponentProps } from '../registry'
import { WorkflowsWidget } from './WorkflowsWidget'
import { WorkflowsWidgetTileFilters } from './WorkflowsWidgetTileFilters'

const CATALOG = getDashboardWidgetCatalogEntry('workflows_list')!
const DEFAULT_CONFIG = CATALOG.defaultConfig as Record<string, unknown>

type WorkflowsWidgetTileStoryProps = DashboardWidgetComponentProps & {
    /** When true, the tile filter bar matches view-only dashboard access. */
    tileFiltersReadOnly?: boolean
}

function WorkflowsWidgetTileStory({
    tileFiltersReadOnly = false,
    ...widgetProps
}: WorkflowsWidgetTileStoryProps): JSX.Element {
    const [config, setConfig] = useState(widgetProps.config)

    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={CATALOG.headerLayout}
                title=""
                defaultTitle={CATALOG.headerTitle ?? CATALOG.label}
                titleHref={CATALOG.titleHref}
                widgetTypeLabel={getDashboardWidgetGroupLabel(CATALOG.groupId)}
                config={config}
                headerMeta={CATALOG.headerMeta}
                description={CATALOG.description}
                showDescription
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            <WorkflowsWidgetTileFilters
                tileId={widgetProps.tileId}
                config={config}
                onUpdateConfig={tileFiltersReadOnly ? undefined : setConfig}
                disabledReason={tileFiltersReadOnly ? DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON : undefined}
            />
            <WidgetCardBody>
                <WorkflowsWidget {...widgetProps} config={config} />
            </WidgetCardBody>
        </WidgetCard>
    )
}

// Storybook CSF requires a string literal `title` derived from catalog groupLabel/label.
const meta: Meta<typeof WorkflowsWidgetTileStory> = {
    title: 'Products/Dashboards/Dashboard Widgets/Widget types/Workflows/Workflow activity',
    component: WorkflowsWidgetTileStory,
    parameters: { layout: 'padded', ...widgetStorybookParameters },
    decorators: widgetTileFrameDecorator,
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
type Story = StoryObj<typeof WorkflowsWidgetTileStory>

export const Populated: Story = {
    args: { result: { results: workflowsSampleRows, hasMore: true, limit: 10 } },
}
export const TileFiltersReadOnly: Story = {
    args: { tileFiltersReadOnly: true, result: { results: workflowsSampleRows, hasMore: false, totalCount: 4 } },
}
export const Loading: Story = {
    args: { loading: true },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export const Empty: Story = {
    args: { config: { ...DEFAULT_CONFIG, status: 'all' }, result: { results: [] } },
}
export const EmptyWithFilters: Story = {
    args: { config: { ...DEFAULT_CONFIG, workflowType: 'loop' }, result: { results: [] } },
}
export const Error: Story = {
    args: { error: 'Failed to load widget data.' },
}
