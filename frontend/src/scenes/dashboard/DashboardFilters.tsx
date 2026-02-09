import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'

import { IconCalendar, IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { QuickFiltersSelectors } from 'lib/components/QuickFilters/QuickFiltersSection'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Scene } from 'scenes/sceneTypes'

import { groupsModel } from '~/models/groupsModel'
import { VariablesForDashboard } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { BreakdownFilter, NodeKind, QuickFilterContext } from '~/queries/schema/schema-general'
import { DashboardMode, InsightLogicProps } from '~/types'

import { DashboardQuickFiltersButton } from './DashboardQuickFiltersModal'
import { dashboardFiltersLogic } from './dashboardFiltersLogic'
import { dashboardLogic } from './dashboardLogic'

export function DashboardPrimaryFilters(): JSX.Element {
    const { dashboard, dashboardMode, hasVariables, effectiveEditBarFilters, canEditDashboard } =
        useValues(dashboardLogic)
    const { setDates, setDashboardMode, triggerDashboardUpdate } = useActions(dashboardLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const canAccessExplicitDateToggle = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_DATE_PICKER_EXPLICIT_DATE_TOGGLE]

    return (
        <>
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
                            if (dashboardMode !== DashboardMode.Edit) {
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

            {canEditDashboard && dashboard && (
                <DashboardQuickFiltersButton
                    context={QuickFilterContext.Dashboards}
                    dashboard={dashboard}
                    updateDashboard={triggerDashboardUpdate}
                />
            )}
        </>
    )
}

export function DashboardQuickFiltersRow(): JSX.Element | null {
    const { dashboard } = useValues(dashboardLogic)
    const filterIds = dashboard?.quick_filter_ids

    // Hide the row if no quick filters are configured
    if (!filterIds || filterIds.length === 0) {
        return null
    }

    return <QuickFiltersSelectors context={QuickFilterContext.Dashboards} filterIds={filterIds} />
}

export function DashboardAdvancedOptionsToggle(): JSX.Element {
    const { dashboard, effectiveEditBarFilters } = useValues(dashboardLogic)
    const filtersLogicProps = { dashboardId: dashboard?.id ?? 0 }
    const { showAdvancedFilters } = useValues(dashboardFiltersLogic(filtersLogicProps))
    const { toggleAdvancedFilters } = useActions(dashboardFiltersLogic(filtersLogicProps))

    // Count active advanced filters
    const propertyFiltersCount = effectiveEditBarFilters.properties?.length || 0
    const hasBreakdown = !!(
        effectiveEditBarFilters.breakdown_filter?.breakdown_type ||
        effectiveEditBarFilters.breakdown_filter?.breakdowns?.length
    )
    const totalAdvancedFilters = propertyFiltersCount + (hasBreakdown ? 1 : 0)

    return (
        <LemonButton
            size="small"
            sideIcon={showAdvancedFilters ? <IconCollapse /> : <IconExpand />}
            onClick={toggleAdvancedFilters}
            title={showAdvancedFilters ? 'Show less' : 'Show more'}
            data-attr="dashboard-advanced-filters-toggle"
        >
            <span className="font-semibold">
                Advanced options
                {totalAdvancedFilters > 0 && <span className="ml-1 text-muted">({totalAdvancedFilters})</span>}
            </span>
        </LemonButton>
    )
}

export function DashboardAdvancedOptions(): JSX.Element | null {
    const {
        dashboard,
        dashboardMode,
        hasVariables,
        effectiveEditBarFilters,
        showEditBarApplyPopover,
        loadingPreview,
        cancellingPreview,
        hasUrlFilters,
    } = useValues(dashboardLogic)
    const { setProperties, setBreakdownFilter, setDashboardMode, applyFilters } = useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { showAdvancedFilters } = useValues(dashboardFiltersLogic({ dashboardId: dashboard?.id ?? 0 }))

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

    if (!showAdvancedFilters) {
        return null
    }

    return (
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
            <div className={clsx('flex gap-2 items-end flex-wrap border rounded p-2 md:[&>*]:grow-0 [&>*]:grow')}>
                <div className={clsx('content-end', { 'h-[61px]': hasVariables })}>
                    <PropertyFilters
                        onChange={(properties) => {
                            if (dashboardMode !== DashboardMode.Edit) {
                                setDashboardMode(DashboardMode.Edit, null)
                            }
                            setProperties(properties)
                        }}
                        pageKey={'dashboard_' + dashboard?.id}
                        propertyFilters={effectiveEditBarFilters.properties}
                        buttonText="Property filter"
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
                                if (dashboardMode !== DashboardMode.Edit) {
                                    setDashboardMode(DashboardMode.Edit, null)
                                }
                                let saved_breakdown_filter: BreakdownFilter | null = breakdown_filter
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
