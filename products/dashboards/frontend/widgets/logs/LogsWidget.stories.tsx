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
import { getDashboardWidgetCatalogEntry, getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON } from '../constants'
import type { DashboardWidgetComponentProps } from '../registry'
import { LogsWidget } from './LogsWidget'
import { logsWidgetSampleLogLines } from './logsWidgetSampleData'
import { LogsWidgetTileFilters } from './LogsWidgetTileFilters'

const LOGS_CATALOG = getDashboardWidgetCatalogEntry('logs_list')!
const DEFAULT_CONFIG = LOGS_CATALOG.defaultConfig as Record<string, unknown>

const logsServicesMock = mswDecorator({
    get: {
        '/api/environments/:team_id/logs/values': () => [
            200,
            { results: [{ name: 'api' }, { name: 'web' }, { name: 'worker' }, { name: 'billing-service' }] },
        ],
    },
})

type LogsWidgetTileStoryProps = DashboardWidgetComponentProps & {
    title?: string
    description?: string
    showDescription?: boolean
    body?: ReactNode
    filterBar?: ReactNode
    /** When true, tile filter bar matches view-only dashboard access (no edit permissions). */
    tileFiltersReadOnly?: boolean
}

function LogsWidgetTileStory({
    title = '',
    description = 'Latest log lines, filterable by severity level and service.',
    showDescription = true,
    body,
    filterBar,
    tileFiltersReadOnly = false,
    ...widgetProps
}: LogsWidgetTileStoryProps): JSX.Element {
    const widgetTypeLabel = getDashboardWidgetGroupLabel(LOGS_CATALOG.groupId)
    const defaultTitle = LOGS_CATALOG.headerTitle ?? LOGS_CATALOG.label

    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={LOGS_CATALOG.headerLayout}
                title={title}
                defaultTitle={defaultTitle}
                titleHref={LOGS_CATALOG.titleHref}
                widgetTypeLabel={widgetTypeLabel}
                config={widgetProps.config}
                headerMeta={LOGS_CATALOG.headerMeta}
                description={description}
                showDescription={showDescription}
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            {filterBar ?? (
                <LogsWidgetTileFilters
                    tileId={widgetProps.tileId ?? 1}
                    config={widgetProps.config}
                    onUpdateConfig={tileFiltersReadOnly ? undefined : widgetProps.onUpdateConfig}
                    disabledReason={tileFiltersReadOnly ? DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON : undefined}
                />
            )}
            <WidgetCardBody>{body ?? <LogsWidget {...widgetProps} />}</WidgetCardBody>
        </WidgetCard>
    )
}

const meta: Meta<typeof LogsWidgetTileStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Logs/Recent logs',
    component: LogsWidgetTileStory,
    parameters: {
        layout: 'padded',
        ...widgetStorybookParameters,
    },
    decorators: [logsServicesMock, ...widgetTileFrameDecorator],
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

type Story = StoryObj<typeof LogsWidgetTileStory>

export const Default: Story = {
    args: {
        title: 'Recent logs',
        config: DEFAULT_CONFIG,
        loading: false,
        result: {
            results: logsWidgetSampleLogLines,
            hasMore: true,
            limit: 10,
            totalCount: 25,
            totalCountCapped: true,
        },
    },
}

export const TileFiltersReadOnly: Story = {
    args: {
        title: 'Recent logs',
        config: { ...DEFAULT_CONFIG, severityLevels: ['error', 'warn'], serviceNames: ['api'], orderBy: 'earliest' },
        tileFiltersReadOnly: true,
        loading: false,
        result: {
            results: logsWidgetSampleLogLines,
            hasMore: true,
            limit: 10,
            totalCount: 25,
            totalCountCapped: true,
        },
    },
    parameters: {
        docs: {
            description: {
                story: 'Tile filter bar when the viewer lacks dashboard edit access — severity, service, and sort are read-only.',
            },
        },
    },
}

export const Loading: Story = {
    args: {
        title: 'Recent logs',
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
        title: 'Recent logs',
        config: DEFAULT_CONFIG,
        loading: false,
        result: { results: [] },
    },
}
