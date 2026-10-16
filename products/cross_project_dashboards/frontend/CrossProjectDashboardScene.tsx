import { useActions, useValues } from 'kea'

import * as chartPng from '@posthog/brand/hoggies/png/chart'
import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { NotFound } from 'lib/components/NotFound'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
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

const HedgehogChart = pngHoggie(chartPng)

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
    } = useValues(crossProjectDashboardLogic)
    const {
        removeTile,
        setDates,
        setInterval,
        setPendingLayouts,
        enterLayoutEdit,
        setTileOverride,
        setTileColor,
        setProperties,
        updateDashboard,
        deleteDashboard,
    } = useActions(crossProjectDashboardLogic)
    const { requestOpenModal } = useActions(addCrossProjectTileLogic({ dashboardId: dashboard?.id ?? '' }))

    if (!featureFlags[FEATURE_FLAGS.CROSS_PROJECT_DASHBOARDS]) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={dashboard?.name ?? ''}
                description={dashboard?.description ?? null}
                resourceType={{ type: 'dashboard' }}
                onNameChange={(name) => updateDashboard({ name })}
                onDescriptionChange={(description) => updateDashboard({ description })}
                canEdit={!!dashboard}
                isLoading={dashboardLoading && !dashboard}
                saveOnBlur
                renameDebounceMs={0}
                descriptionMaxLength={4000}
                actions={
                    dashboard ? (
                        <div className="flex flex-wrap items-center gap-2">
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
                                onClick={requestOpenModal}
                                data-attr="cross-project-add-tile"
                            >
                                Add insight
                            </LemonButton>
                            <More
                                data-attr="cross-project-dashboard-more"
                                overlay={
                                    <LemonButton
                                        status="danger"
                                        fullWidth
                                        onClick={deleteDashboard}
                                        data-attr="cross-project-dashboard-delete"
                                    >
                                        Delete dashboard
                                    </LemonButton>
                                }
                            />
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
                // Same illustration and layout as the empty single-project dashboard.
                <ProductIntroduction
                    thingName="cross-project-insight"
                    titleOverride="Build your dashboard"
                    description="Add insights from any project you have access to. Each tile shows data from its own project."
                    customHog={HedgehogChart}
                    hogLayout="responsive"
                    useMainContentContainerQueries
                    className="mt-2 mb-2 py-4 @min-[48rem]/main-content:py-14"
                    actionElementOverride={
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            onClick={requestOpenModal}
                            data-attr="cross-project-dashboard-empty-add-insight"
                        >
                            Add insight
                        </LemonButton>
                    }
                />
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
