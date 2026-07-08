import type { Meta, StoryObj } from '@storybook/react'
import React from 'react'

import { DashboardPlacement } from '~/types'

import {
    DASHBOARD_WIDGET_CATALOG,
    getDashboardWidgetCatalogEntry,
    getDashboardWidgetGroupLabel,
    type DashboardWidgetCatalogKey,
} from '../../widget_types/catalog'
import { getDashboardWidgetDefinition } from '../../widgets/registry'
import { WidgetCard } from './WidgetCard'
import { WidgetCardBody } from './WidgetCardBody'
import { WidgetCardHeader, widgetCardShouldHideMoreButton } from './WidgetCardHeader'
import { mockMoreOverlay, widgetStorybookParameters, withErrorTrackingProjectState } from './widgetCardStoryFixtures'
import { getWidgetOverviewDemoState } from './widgetOverviewStoryFixtures'

// Dashboard grid row height — see DashboardItems BASE_ROW_HEIGHT.
const DASHBOARD_ROW_HEIGHT_PX = 80
// Overview tiles render taller than catalog defaultLayout.h so widget bodies have room at story scale.
const OVERVIEW_TILE_HEIGHT_ROWS = 8
const OVERVIEW_TILE_MIN_HEIGHT = OVERVIEW_TILE_HEIGHT_ROWS * DASHBOARD_ROW_HEIGHT_PX

// Renders all catalog keys — add demo state per type in widgetOverviewStoryFixtures.ts (CONTRIBUTING.md).
const dashboardWidgetCatalogKeys = Object.keys(DASHBOARD_WIDGET_CATALOG) as DashboardWidgetCatalogKey[]

function DashboardWidgetOverviewTile({
    catalogKey,
    tileId,
}: {
    catalogKey: DashboardWidgetCatalogKey
    tileId: number
}): JSX.Element | null {
    const catalogEntry = getDashboardWidgetCatalogEntry(catalogKey)
    const definition = getDashboardWidgetDefinition(catalogKey)
    const demoState = getWidgetOverviewDemoState(catalogKey)

    if (!definition || !catalogEntry) {
        return null
    }

    const WidgetComponent = definition.Component
    const widgetTypeLabel = getDashboardWidgetGroupLabel(catalogEntry.groupId)
    const defaultTitle = catalogEntry.headerTitle ?? catalogEntry.label

    return (
        <div
            className="min-h-0 rounded border border-dashed border-border bg-bg-light p-4"
            style={{ minHeight: OVERVIEW_TILE_MIN_HEIGHT }}
        >
            <WidgetCard className="h-full">
                <WidgetCardHeader
                    layout={catalogEntry.headerLayout}
                    title={demoState.title ?? ''}
                    defaultTitle={defaultTitle}
                    titleHref={catalogEntry.titleHref}
                    widgetTypeLabel={widgetTypeLabel}
                    config={demoState.config}
                    headerMeta={catalogEntry.headerMeta}
                    description={demoState.description}
                    showDescription={demoState.showDescription ?? true}
                    loading={demoState.loading}
                    shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                    moreButtonOverlay={mockMoreOverlay}
                />
                <WidgetCardBody error={demoState.cardError}>
                    <React.Suspense fallback={null}>
                        <WidgetComponent
                            tileId={tileId}
                            config={demoState.config}
                            loading={demoState.loading}
                            result={demoState.result}
                            onUpdateConfig={() => undefined}
                            onRefresh={() => undefined}
                        />
                    </React.Suspense>
                </WidgetCardBody>
            </WidgetCard>
        </div>
    )
}

function DashboardWidgetsOverview(): JSX.Element {
    return (
        <div className="mx-auto w-full max-w-screen-2xl p-6">
            <div className="grid grid-cols-1 gap-8 xl:grid-cols-2">
                {dashboardWidgetCatalogKeys.map((catalogKey, index) => (
                    <DashboardWidgetOverviewTile key={catalogKey} catalogKey={catalogKey} tileId={index + 1} />
                ))}
            </div>
        </div>
    )
}

const dashboardOverviewFrameDecorator = [
    (Story: React.ComponentType): JSX.Element => (
        <div className="min-h-screen bg-bg-light">
            <Story />
        </div>
    ),
]

const meta: Meta<typeof DashboardWidgetsOverview> = {
    title: 'Dashboards/Dashboard Widgets/Overview',
    component: DashboardWidgetsOverview,
    parameters: {
        layout: 'fullscreen',
        ...widgetStorybookParameters,
        docs: {
            description: {
                component:
                    'All registered dashboard widget types at dashboard scale. New catalog entries appear here automatically.',
            },
        },
    },
    decorators: [withErrorTrackingProjectState(true), ...dashboardOverviewFrameDecorator],
}

export default meta

type Story = StoryObj<typeof DashboardWidgetsOverview>

export const AllWidgetTypes: Story = {}
