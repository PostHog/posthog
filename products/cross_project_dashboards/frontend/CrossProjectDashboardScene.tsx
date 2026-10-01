import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { NotFound } from 'lib/components/NotFound'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import type { IntervalType } from '~/types'

import { addCrossProjectTileLogic } from './addCrossProjectTileLogic'
import { AddCrossProjectTileModal } from './AddCrossProjectTileModal'
import { CrossProjectDashboardGrid } from './CrossProjectDashboardGrid'
import { CrossProjectDashboardLayoutActions } from './CrossProjectDashboardLayoutActions'
import { crossProjectDashboardLogic } from './crossProjectDashboardLogic'
import { openCrossProjectTileOverrideDialog } from './openCrossProjectTileOverrideDialog'

export const scene: SceneExport = {
    component: CrossProjectDashboardScene,
    logic: crossProjectDashboardLogic,
    paramsToProps: ({ params: { id } }): (typeof crossProjectDashboardLogic)['props'] => ({ id }),
}

export function CrossProjectDashboardScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        dashboard,
        dashboardLoading,
        tiles,
        dashboardFilters,
        tileProjects,
        timezonesDiverge,
        missingPropertyKeys,
        layoutEditMode,
        gridLayouts,
        hasUnsavedLayoutChanges,
    } = useValues(crossProjectDashboardLogic)
    const {
        removeTile,
        setDates,
        setInterval,
        setPendingLayouts,
        enterLayoutEdit,
        exitLayoutEdit,
        setTileOverride,
        setTileColor,
        setProperties,
    } = useActions(crossProjectDashboardLogic)
    const { openModal } = useActions(addCrossProjectTileLogic({ dashboardId: dashboard?.id ?? '' }))

    if (!featureFlags[FEATURE_FLAGS.CROSS_PROJECT_DASHBOARDS]) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={dashboard?.name ?? ''}
                description={dashboard?.description ?? null}
                resourceType={{ type: 'dashboard' }}
                actions={
                    dashboard ? (
                        <div className="flex items-center gap-2">
                            <DateFilter
                                dateFrom={dashboardFilters.date_from ?? null}
                                dateTo={dashboardFilters.date_to ?? null}
                                onChange={setDates}
                            />
                            <LemonSelect<IntervalType | null>
                                size="small"
                                value={dashboardFilters.interval ?? null}
                                onChange={setInterval}
                                dropdownMatchSelectWidth={false}
                                data-attr="cross-project-interval-filter"
                                options={[
                                    { value: null, label: 'Default interval' },
                                    { value: 'hour', label: 'Hour' },
                                    { value: 'day', label: 'Day' },
                                    { value: 'week', label: 'Week' },
                                    { value: 'month', label: 'Month' },
                                ]}
                            />
                            <CrossProjectDashboardLayoutActions />
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                onClick={() => {
                                    if (
                                        hasUnsavedLayoutChanges &&
                                        !window.confirm(
                                            'Discard unsaved layout changes?\nAdding an insight reloads the dashboard and discards them.'
                                        )
                                    ) {
                                        return
                                    }
                                    if (layoutEditMode) {
                                        exitLayoutEdit()
                                    }
                                    openModal()
                                }}
                                data-attr="cross-project-add-tile"
                            >
                                Add insight
                            </LemonButton>
                        </div>
                    ) : undefined
                }
            />
            {dashboard ? (
                <PropertyFilters
                    pageKey={`cross-project-dashboard-${dashboard.id}`}
                    propertyFilters={dashboardFilters.properties ?? []}
                    onChange={setProperties}
                    taxonomicGroupTypes={[
                        // Only groups whose filter travels by name. A cohort, group or flag filter
                        // carries an id that means something different in each project, and the API
                        // refuses it.
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.EventMetadata,
                    ]}
                />
            ) : null}
            {/* A reload after a filter change keeps the grid mounted, so only the first load shows a skeleton. */}
            {dashboardLoading && !dashboard ? (
                <LemonSkeleton className="h-60 w-full" />
            ) : !dashboard ? (
                <p>This dashboard is not available.</p>
            ) : tiles.length === 0 ? (
                <p>No tiles yet. Add an insight from any project you can reach.</p>
            ) : (
                <CrossProjectDashboardGrid
                    missingPropertyKeys={missingPropertyKeys}
                    tiles={tiles}
                    tileProjects={tileProjects}
                    timezonesDiverge={timezonesDiverge}
                    dashboardFilters={dashboardFilters}
                    layouts={gridLayouts}
                    layoutEditMode={layoutEditMode}
                    onEnterLayoutEdit={enterLayoutEdit}
                    onLayoutsChange={setPendingLayouts}
                    onSetTileOverride={(tile) =>
                        openCrossProjectTileOverrideDialog(tile, (overrides) => setTileOverride(tile.id, overrides))
                    }
                    onSetTileColor={setTileColor}
                    onRemoveTile={removeTile}
                />
            )}
            {dashboard ? <AddCrossProjectTileModal dashboardId={dashboard.id} /> : null}
        </SceneContent>
    )
}
