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
import { activityEventsSampleEvents } from './activityEventsSampleData'
import { ActivityEventsWidget } from './ActivityEventsWidget'
import { ActivityEventsWidgetTileFilters } from './ActivityEventsWidgetTileFilters'

const ACTIVITY_EVENTS_CATALOG = getDashboardWidgetCatalogEntry('activity_events_list')!
const DEFAULT_CONFIG = ACTIVITY_EVENTS_CATALOG.defaultConfig as Record<string, unknown>

type ActivityEventsWidgetTileStoryProps = DashboardWidgetComponentProps & {
    title?: string
    description?: string
    showDescription?: boolean
    body?: ReactNode
    filterBar?: ReactNode
    /** When true, tile filter bar matches view-only dashboard access (no edit permissions). */
    tileFiltersReadOnly?: boolean
}

function ActivityEventsWidgetTileStory({
    title = '',
    description = 'Latest events captured in this project, as on Activity > Explore.',
    showDescription = true,
    body,
    filterBar,
    tileFiltersReadOnly = false,
    ...widgetProps
}: ActivityEventsWidgetTileStoryProps): JSX.Element {
    const widgetTypeLabel = getDashboardWidgetGroupLabel(ACTIVITY_EVENTS_CATALOG.groupId)
    const defaultTitle = ACTIVITY_EVENTS_CATALOG.headerTitle ?? ACTIVITY_EVENTS_CATALOG.label

    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={ACTIVITY_EVENTS_CATALOG.headerLayout}
                title={title}
                defaultTitle={defaultTitle}
                titleHref={ACTIVITY_EVENTS_CATALOG.titleHref}
                widgetTypeLabel={widgetTypeLabel}
                config={widgetProps.config}
                headerMeta={ACTIVITY_EVENTS_CATALOG.headerMeta}
                description={description}
                showDescription={showDescription}
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            {filterBar ?? (
                <ActivityEventsWidgetTileFilters
                    tileId={widgetProps.tileId ?? 1}
                    config={widgetProps.config}
                    onUpdateConfig={tileFiltersReadOnly ? undefined : widgetProps.onUpdateConfig}
                    disabledReason={tileFiltersReadOnly ? DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON : undefined}
                />
            )}
            <WidgetCardBody>{body ?? <ActivityEventsWidget {...widgetProps} />}</WidgetCardBody>
        </WidgetCard>
    )
}

const meta: Meta<typeof ActivityEventsWidgetTileStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Activity/Recent events',
    component: ActivityEventsWidgetTileStory,
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

type Story = StoryObj<typeof ActivityEventsWidgetTileStory>

export const Default: Story = {
    args: {
        title: 'Recent events',
        config: DEFAULT_CONFIG,
        loading: false,
        result: {
            results: activityEventsSampleEvents,
            hasMore: true,
            limit: 10,
            totalCount: 25,
            totalCountCapped: true,
        },
    },
}

export const TileFiltersReadOnly: Story = {
    args: {
        title: 'Recent events',
        config: { ...DEFAULT_CONFIG, dateRange: { date_from: '-7d' } },
        tileFiltersReadOnly: true,
        loading: false,
        result: {
            results: activityEventsSampleEvents,
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
        title: 'Recent events',
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
        title: 'Recent events',
        config: DEFAULT_CONFIG,
        loading: false,
        result: { results: [] },
    },
}
