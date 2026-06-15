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
    withErrorTrackingProjectState,
} from '../../components/WidgetCard/widgetCardStoryFixtures'
import { errorTrackingSampleIssues } from '../../components/WidgetCard/widgetOverviewStoryFixtures'
import { getDashboardWidgetCatalogEntry, getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { useWidgetAvailability } from '../../widget_types/widgetAvailability'
import { DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON } from '../constants'
import type { DashboardWidgetComponentProps } from '../registry'
import { ErrorTrackingWidget } from './ErrorTrackingWidget'
import { ErrorTrackingWidgetTileFilters } from './ErrorTrackingWidgetTileFilters'

const ERROR_TRACKING_CATALOG = getDashboardWidgetCatalogEntry('error_tracking_list')!
const DEFAULT_CONFIG = ERROR_TRACKING_CATALOG.defaultConfig as Record<string, unknown>

type ErrorTrackingWidgetTileStoryProps = DashboardWidgetComponentProps & {
    title?: string
    description?: string
    showDescription?: boolean
    body?: ReactNode
    /** When true, tile filter bar matches view-only dashboard access (no edit permissions). */
    tileFiltersReadOnly?: boolean
}

function ErrorTrackingWidgetTileStory({
    title = '',
    description = 'Track the most common errors affecting your users.',
    showDescription = true,
    body,
    tileFiltersReadOnly = false,
    ...widgetProps
}: ErrorTrackingWidgetTileStoryProps): JSX.Element {
    const widgetTypeLabel = getDashboardWidgetGroupLabel(ERROR_TRACKING_CATALOG.groupId)
    const defaultTitle = ERROR_TRACKING_CATALOG.headerTitle ?? ERROR_TRACKING_CATALOG.label
    const { isAvailable: showTileFilters } = useWidgetAvailability(ERROR_TRACKING_CATALOG.availability)

    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={ERROR_TRACKING_CATALOG.headerLayout}
                title={title}
                defaultTitle={defaultTitle}
                titleHref={ERROR_TRACKING_CATALOG.titleHref}
                widgetTypeLabel={widgetTypeLabel}
                config={widgetProps.config}
                headerMeta={ERROR_TRACKING_CATALOG.headerMeta}
                description={description}
                showDescription={showDescription}
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            {showTileFilters ? (
                <ErrorTrackingWidgetTileFilters
                    tileId={widgetProps.tileId}
                    config={widgetProps.config}
                    onUpdateConfig={tileFiltersReadOnly ? undefined : widgetProps.onUpdateConfig}
                    disabledReason={tileFiltersReadOnly ? DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON : undefined}
                />
            ) : null}
            <WidgetCardBody>{body ?? <ErrorTrackingWidget {...widgetProps} />}</WidgetCardBody>
        </WidgetCard>
    )
}

// Storybook CSF requires a string literal `title` derived from catalog groupLabel/label.
const meta: Meta<typeof ErrorTrackingWidgetTileStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Error tracking/Top issues',
    component: ErrorTrackingWidgetTileStory,
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

type Story = StoryObj<typeof ErrorTrackingWidgetTileStory>

export const TileFiltersReadOnly: Story = {
    decorators: [withErrorTrackingProjectState(true)],
    args: {
        title: 'Top issues',
        config: {
            ...DEFAULT_CONFIG,
            status: 'resolved',
            dateRange: { date_from: '-30d' },
        },
        tileFiltersReadOnly: true,
        loading: false,
        result: {
            results: errorTrackingSampleIssues,
            hasMore: true,
            limit: 10,
        },
    },
    parameters: {
        docs: {
            description: {
                story: 'Tile filter bar when the viewer lacks dashboard edit access — filters shown as read-only values.',
            },
        },
    },
}

export const Default: Story = {
    decorators: [withErrorTrackingProjectState(true)],
    args: {
        title: 'Top issues',
        config: { ...DEFAULT_CONFIG, orderBy: 'occurrences' },
        loading: false,
        result: {
            results: errorTrackingSampleIssues,
            hasMore: true,
            limit: 10,
        },
    },
}

export const Loading: Story = {
    decorators: [withErrorTrackingProjectState(true)],
    args: {
        title: 'Top issues',
        config: DEFAULT_CONFIG,
        loading: true,
        result: null,
    },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}

export const Empty: Story = {
    decorators: [withErrorTrackingProjectState(true)],
    args: {
        title: 'Top issues',
        config: DEFAULT_CONFIG,
        loading: false,
        result: { results: [] },
    },
    parameters: {
        docs: {
            description: {
                story: 'Celebratory empty state when no issues match the widget filters.',
            },
        },
    },
}

export const SetupUnavailable: Story = {
    args: {
        title: 'Top issues',
        config: DEFAULT_CONFIG,
        loading: false,
        result: null,
    },
    decorators: [withErrorTrackingProjectState(false)],
    parameters: {
        docs: {
            description: {
                story: 'Uses the shared `ErrorTrackingIngestionPrompt` from error tracking (via `ErrorTrackingWidget`) when exception autocapture is disabled and no exceptions have been captured.',
            },
        },
    },
}
