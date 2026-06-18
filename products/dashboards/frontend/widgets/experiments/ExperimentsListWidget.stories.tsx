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
import { experimentsSampleListRows } from '../../components/WidgetCard/widgetOverviewStoryFixtures'
import { getDashboardWidgetCatalogEntry, getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { useWidgetAvailability } from '../../widget_types/widgetAvailability'
import { DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON } from '../constants'
import type { DashboardWidgetComponentProps } from '../registry'
import { ExperimentsListWidget } from './ExperimentsListWidget'
import { ExperimentsListWidgetTileFilters } from './ExperimentsListWidgetTileFilters'

const EXPERIMENTS_LIST_CATALOG = getDashboardWidgetCatalogEntry('experiments_list')!
const DEFAULT_CONFIG = EXPERIMENTS_LIST_CATALOG.defaultConfig as Record<string, unknown>

type ExperimentsListWidgetTileStoryProps = DashboardWidgetComponentProps & {
    title?: string
    description?: string
    showDescription?: boolean
    body?: ReactNode
    /** When true, tile filter bar matches view-only dashboard access (no edit permissions). */
    tileFiltersReadOnly?: boolean
}

function ExperimentsListWidgetTileStory({
    title = '',
    description = EXPERIMENTS_LIST_CATALOG.description,
    showDescription = true,
    body,
    tileFiltersReadOnly = false,
    ...widgetProps
}: ExperimentsListWidgetTileStoryProps): JSX.Element {
    const widgetTypeLabel = getDashboardWidgetGroupLabel(EXPERIMENTS_LIST_CATALOG.groupId)
    const defaultTitle = EXPERIMENTS_LIST_CATALOG.headerTitle ?? EXPERIMENTS_LIST_CATALOG.label
    const { isAvailable: showTileFilters } = useWidgetAvailability(EXPERIMENTS_LIST_CATALOG.availability)

    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={EXPERIMENTS_LIST_CATALOG.headerLayout}
                title={title}
                defaultTitle={defaultTitle}
                titleHref={EXPERIMENTS_LIST_CATALOG.titleHref}
                widgetTypeLabel={widgetTypeLabel}
                config={widgetProps.config}
                headerMeta={EXPERIMENTS_LIST_CATALOG.headerMeta}
                description={description}
                showDescription={showDescription}
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            {showTileFilters ? (
                <ExperimentsListWidgetTileFilters
                    tileId={widgetProps.tileId}
                    config={widgetProps.config}
                    onUpdateConfig={tileFiltersReadOnly ? undefined : widgetProps.onUpdateConfig}
                    disabledReason={tileFiltersReadOnly ? DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON : undefined}
                />
            ) : null}
            <WidgetCardBody>{body ?? <ExperimentsListWidget {...widgetProps} />}</WidgetCardBody>
        </WidgetCard>
    )
}

// Storybook CSF requires a string literal `title` derived from catalog groupLabel/label.
const meta: Meta<typeof ExperimentsListWidgetTileStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Experiments/Experiments',
    component: ExperimentsListWidgetTileStory,
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

type Story = StoryObj<typeof ExperimentsListWidgetTileStory>

export const Default: Story = {
    args: {
        title: 'Experiments',
        loading: false,
        result: {
            results: experimentsSampleListRows,
            hasMore: true,
            limit: 10,
            totalCount: 12,
            totalCountCapped: false,
        },
    },
}

export const TileFiltersReadOnly: Story = {
    args: {
        title: 'Experiments',
        config: { ...DEFAULT_CONFIG, status: 'running' },
        tileFiltersReadOnly: true,
        loading: false,
        result: {
            results: experimentsSampleListRows,
            hasMore: true,
            limit: 10,
            totalCount: 12,
            totalCountCapped: false,
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

export const Loading: Story = {
    args: {
        title: 'Experiments',
        loading: true,
        result: null,
    },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}

export const Empty: Story = {
    args: {
        title: 'Experiments',
        loading: false,
        result: { results: [] },
    },
    parameters: {
        docs: {
            description: {
                story: 'Empty state with a "New experiment" CTA when the project has no experiments yet.',
            },
        },
    },
}
