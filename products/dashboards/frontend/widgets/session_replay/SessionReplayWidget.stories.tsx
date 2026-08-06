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
    withSessionReplayProjectState,
} from '../../components/WidgetCard/widgetCardStoryFixtures'
import { sessionReplaySampleRecordings } from '../../components/WidgetCard/widgetOverviewStoryFixtures'
import { WidgetRuntimeAvailabilityGuard } from '../../components/WidgetRuntimeAvailabilityGuard/WidgetRuntimeAvailabilityGuard'
import { getDashboardWidgetCatalogEntry, getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { useWidgetAvailability } from '../../widget_types/widgetAvailability'
import { DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON } from '../constants'
import type { DashboardWidgetComponentProps } from '../registry'
import { SessionReplayWidget } from './SessionReplayWidget'
import { SessionReplayWidgetTileFilters } from './SessionReplayWidgetTileFilters'

const SESSION_REPLAY_CATALOG = getDashboardWidgetCatalogEntry('session_replay_list')!
const DEFAULT_CONFIG = SESSION_REPLAY_CATALOG.defaultConfig as Record<string, unknown>

type SessionReplayWidgetTileStoryProps = DashboardWidgetComponentProps & {
    title?: string
    description?: string
    showDescription?: boolean
    body?: ReactNode
    filterBar?: ReactNode
    /** When true, tile filter bar matches view-only dashboard access (no edit permissions). */
    tileFiltersReadOnly?: boolean
}

function SessionReplayWidgetTileStory({
    title = '',
    description = 'Recent session recordings you can open in the replay player.',
    showDescription = true,
    body,
    filterBar,
    tileFiltersReadOnly = false,
    ...widgetProps
}: SessionReplayWidgetTileStoryProps): JSX.Element {
    const widgetTypeLabel = getDashboardWidgetGroupLabel(SESSION_REPLAY_CATALOG.groupId)
    const defaultTitle = SESSION_REPLAY_CATALOG.headerTitle ?? SESSION_REPLAY_CATALOG.label
    const { isAvailable: showTileFilters } = useWidgetAvailability(SESSION_REPLAY_CATALOG.availability)

    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={SESSION_REPLAY_CATALOG.headerLayout}
                title={title}
                defaultTitle={defaultTitle}
                titleHref={SESSION_REPLAY_CATALOG.titleHref}
                widgetTypeLabel={widgetTypeLabel}
                config={widgetProps.config}
                headerMeta={SESSION_REPLAY_CATALOG.headerMeta}
                description={description}
                showDescription={showDescription}
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            {showTileFilters
                ? (filterBar ?? (
                      <SessionReplayWidgetTileFilters
                          tileId={widgetProps.tileId ?? 1}
                          config={widgetProps.config}
                          onUpdateConfig={tileFiltersReadOnly ? undefined : widgetProps.onUpdateConfig}
                          disabledReason={
                              tileFiltersReadOnly ? DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON : undefined
                          }
                      />
                  ))
                : null}
            <WidgetCardBody>{body ?? <SessionReplayWidget {...widgetProps} />}</WidgetCardBody>
        </WidgetCard>
    )
}

const meta: Meta<typeof SessionReplayWidgetTileStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Session replay/Recent recordings',
    component: SessionReplayWidgetTileStory,
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

type Story = StoryObj<typeof SessionReplayWidgetTileStory>

export const Default: Story = {
    decorators: [withSessionReplayProjectState(true)],
    args: {
        title: 'Recent recordings',
        config: { ...DEFAULT_CONFIG, orderBy: 'start_time' },
        loading: false,
        result: {
            results: sessionReplaySampleRecordings,
            hasMore: true,
            limit: 10,
            totalCount: 25,
            totalCountCapped: true,
        },
    },
}

export const TileFiltersReadOnly: Story = {
    decorators: [withSessionReplayProjectState(true)],
    args: {
        title: 'Recent recordings',
        config: {
            ...DEFAULT_CONFIG,
            dateRange: { date_from: '-30d' },
            widgetFilters: {
                'qf-browser': {
                    filterId: 'qf-browser',
                    propertyName: '$browser',
                    optionId: 'opt-chrome',
                    operator: 'exact',
                    value: 'Chrome',
                },
            },
        },
        tileFiltersReadOnly: true,
        loading: false,
        result: {
            results: sessionReplaySampleRecordings,
            hasMore: true,
            limit: 10,
            totalCount: 25,
            totalCountCapped: true,
        },
    },
    parameters: {
        docs: {
            description: {
                story: 'Tile filter bar when the viewer lacks dashboard edit access — date range and property filters are disabled.',
            },
        },
    },
}

export const Loading: Story = {
    decorators: [withSessionReplayProjectState(true)],
    args: {
        title: 'Recent recordings',
        config: DEFAULT_CONFIG,
        loading: true,
        result: null,
    },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}

export const Empty: Story = {
    decorators: [withSessionReplayProjectState(true)],
    args: {
        title: 'Recent recordings',
        config: DEFAULT_CONFIG,
        loading: false,
        result: { results: [] },
    },
}

export const SetupUnavailable: Story = {
    decorators: [withSessionReplayProjectState(false)],
    render: (args: SessionReplayWidgetTileStoryProps) => (
        <SessionReplayWidgetTileStory
            {...args}
            body={
                <WidgetRuntimeAvailabilityGuard availability={SESSION_REPLAY_CATALOG.availability}>
                    <SessionReplayWidget {...args} />
                </WidgetRuntimeAvailabilityGuard>
            }
        />
    ),
    args: {
        title: 'Recent recordings',
        config: DEFAULT_CONFIG,
        loading: false,
        result: null,
    },
    parameters: {
        docs: {
            description: {
                story: 'Uses catalog `session_replay_enabled` availability via `WidgetRuntimeAvailabilityGuard` when session replay is disabled.',
            },
        },
    },
}
