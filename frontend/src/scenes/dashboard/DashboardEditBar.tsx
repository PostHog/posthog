import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardFiltersLogic } from 'scenes/dashboard/dashboardFiltersLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Scene } from 'scenes/sceneTypes'

import { groupsModel } from '~/models/groupsModel'
import { VariablesForDashboard } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { BreakdownFilter, DashboardFilter, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, DashboardMode, InsightLogicProps } from '~/types'

function useDashboardFilters(
    dashboardId: number | undefined,
    useDensityV2: boolean
): {
    effectiveEditBarFilters: DashboardFilter
    showEditBarApplyPopover: boolean
    hasUrlFilters: boolean
    setDates: (dateFrom: string | null, dateTo: string | null | undefined, explicitDate?: boolean) => void
    setProperties: (properties: AnyPropertyFilter[] | null) => void
    setBreakdownFilter: (breakdownFilter: BreakdownFilter | null) => void
    applyFilters: () => void
} {
    const filtersLogicProps = dashboardId ? { id: dashboardId } : { id: 0 }
    const v2Values = useValues(dashboardFiltersLogic(filtersLogicProps))
    const v2Actions = useActions(dashboardFiltersLogic(filtersLogicProps))
    const v1Values = useValues(dashboardLogic)
    const v1Actions = useActions(dashboardLogic)

    if (useDensityV2 && dashboardId) {
        return {
            effectiveEditBarFilters: v2Values.effectiveEditBarFilters,
            showEditBarApplyPopover: v2Values.showEditBarApplyPopover,
            hasUrlFilters: v2Values.hasUrlFilters,
            setDates: v2Actions.setDates,
            setProperties: v2Actions.setProperties,
            setBreakdownFilter: v2Actions.setBreakdownFilter,
            applyFilters: v2Actions.applyFilters,
        }
    }
    return {
        effectiveEditBarFilters: v1Values.effectiveEditBarFilters,
        showEditBarApplyPopover: v1Values.showEditBarApplyPopover,
        hasUrlFilters: v1Values.hasUrlFilters,
        setDates: v1Actions.setDates,
        setProperties: v1Actions.setProperties,
        setBreakdownFilter: v1Actions.setBreakdownFilter,
        applyFilters: v1Actions.applyFilters,
    }
}

export function DashboardEditBar(): JSX.Element {
    const { dashboard, dashboardMode, hasVariables, loadingPreview, cancellingPreview } = useValues(dashboardLogic)
    const { setDashboardMode } = useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const { featureFlags } = useValues(featureFlagLogic)
    const useDensityV2 = !!featureFlags[FEATURE_FLAGS.DASHBOARD_DENSITY_V2]
    const canAccessExplicitDateToggle = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_DATE_PICKER_EXPLICIT_DATE_TOGGLE]

    const {
        effectiveEditBarFilters,
        showEditBarApplyPopover,
        hasUrlFilters,
        setDates,
        setProperties,
        setBreakdownFilter,
        applyFilters,
    } = useDashboardFilters(dashboard?.id, useDensityV2)

    const insightProps: InsightLogicProps = {
        dashboardItemId: 'new',
        dashboardId: dashboard?.id,
        cachedInsight: null,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [],
            },
        },
    }

    return (
        // Only show preview button for large dashboards where we don't automatically preview filter changes */
        <Popover
            visible={showEditBarApplyPopover}
            overlay={
                <div className="flex items-center gap-2 m-1">
                    <LemonButton
                        onClick={() =>
                            setDashboardMode(
                                hasUrlFilters ? dashboardMode : null,
                                DashboardEventSource.DashboardHeaderDiscardChanges
                            )
                        }
                        loading={cancellingPreview}
                        type="secondary"
                        size="small"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton onClick={applyFilters} loading={loadingPreview} type="primary" size="small">
                        Apply filters and preview
                    </LemonButton>
                </div>
            }
            placement="bottom"
            showArrow
        >
            <div
                className={clsx(
                    'flex gap-2 items-end flex-wrap border md:[&>*]:grow-0 [&>*]:grow',
                    dashboardMode === DashboardMode.Edit
                        ? '-m-1.5 p-1.5 border-primary border-dashed rounded-lg'
                        : 'border-transparent'
                )}
            >
                <div className={clsx('content-end', { 'h-[61px]': hasVariables })}>
                    <AppShortcut
                        name="DashboardDateFilter"
                        keybind={[keyBinds.dateFilter]}
                        intent="Date filter"
                        interaction="click"
                        scope={Scene.Dashboard}
                    >
                        <DateFilter
                            showCustom
                            showExplicitDateToggle={canAccessExplicitDateToggle}
                            allowTimePrecision
                            allowFixedRangeWithTime
                            dateFrom={effectiveEditBarFilters.date_from}
                            dateTo={effectiveEditBarFilters.date_to}
                            explicitDate={effectiveEditBarFilters.explicitDate}
                            onChange={(from_date, to_date, explicitDate) => {
                                if (!useDensityV2 && dashboardMode !== DashboardMode.Edit) {
                                    setDashboardMode(DashboardMode.Edit, null)
                                }
                                setDates(from_date, to_date, explicitDate)
                            }}
                            makeLabel={(key) => (
                                <>
                                    <IconCalendar />
                                    <span className="hide-when-small"> {key}</span>
                                </>
                            )}
                        />
                    </AppShortcut>
                </div>
                <div className={clsx('content-end', { 'h-[61px]': hasVariables })}>
                    <PropertyFilters
                        onChange={(properties) => {
                            if (!useDensityV2 && dashboardMode !== DashboardMode.Edit) {
                                setDashboardMode(DashboardMode.Edit, null)
                            }
                            setProperties(properties)
                        }}
                        pageKey={'dashboard_' + dashboard?.id}
                        propertyFilters={effectiveEditBarFilters.properties}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.EventFeatureFlags,
                            TaxonomicFilterGroupType.EventMetadata,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.Elements,
                            TaxonomicFilterGroupType.SessionProperties,
                            TaxonomicFilterGroupType.HogQLExpression,
                            TaxonomicFilterGroupType.DataWarehousePersonProperties,
                        ]}
                    />
                </div>
                <div className={clsx('content-end', { 'h-[61px]': hasVariables })}>
                    <BindLogic logic={insightLogic} props={insightProps}>
                        <TaxonomicBreakdownFilter
                            insightProps={insightProps}
                            breakdownFilter={effectiveEditBarFilters.breakdown_filter}
                            isTrends={false}
                            showLabel={false}
                            updateBreakdownFilter={(breakdown_filter) => {
                                if (!useDensityV2 && dashboardMode !== DashboardMode.Edit) {
                                    setDashboardMode(DashboardMode.Edit, null)
                                }
                                let saved_breakdown_filter: BreakdownFilter | null = breakdown_filter
                                // taxonomicBreakdownFilterLogic can generate an empty breakdown_filter object
                                if (
                                    breakdown_filter &&
                                    !breakdown_filter.breakdown_type &&
                                    !breakdown_filter.breakdowns
                                ) {
                                    saved_breakdown_filter = null
                                }
                                setBreakdownFilter(saved_breakdown_filter)
                            }}
                            updateDisplay={() => {}}
                            disablePropertyInfo
                            size="small"
                        />
                    </BindLogic>
                </div>

                <VariablesForDashboard />
            </div>
        </Popover>
    )
}
