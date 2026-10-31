import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconCalendar, IconPalette } from '@posthog/icons'
import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar/FilterBar'
import { FilterBarAction } from 'lib/components/FilterBar/FilterBarAction'
import { FilterBarBreakdown } from 'lib/components/FilterBar/FilterBarBreakdown'
import { FilterBarDateRange } from 'lib/components/FilterBar/FilterBarDateRange'
import { FilterBarInterval } from 'lib/components/FilterBar/FilterBarInterval'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import {
    DashboardControl,
    dashboardControlScopeText,
    isDashboardControlHidden,
} from 'scenes/dashboard/dashboardControls'
import { DashboardEditBarAdvancedFilters } from 'scenes/dashboard/DashboardEditBarAdvancedFilters'
import { dashboardInsightColorsModalLogic } from 'scenes/dashboard/dashboardInsightColorsModalLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Scene } from 'scenes/sceneTypes'

import { groupsModel } from '~/models/groupsModel'
import { VariablesForDashboard } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { BreakdownFilter, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, DashboardPlacement, InsightLogicProps, IntervalType } from '~/types'

import { DashboardComparisonControl } from 'products/dashboards/frontend/components/DashboardFilterBarControls/DashboardComparisonControl'
import { DashboardTestAccountsControl } from 'products/dashboards/frontend/components/DashboardFilterBarControls/DashboardTestAccountsControl'
import { DashboardUnsavedChangesMenu } from 'products/dashboards/frontend/dashboardSettings/DashboardUnsavedChangesMenu'
import { DashboardMetricVariables } from 'products/metrics/frontend/components/dashboardVariables/DashboardMetricVariables'
import { TaxonomicBreakdownFilter } from 'products/product_analytics/frontend/insights/editor/filters/BreakdownFilter/TaxonomicBreakdownFilter'

interface DashboardEditBarProps {
    showDateFilter?: boolean
    className?: string
}

/** Wraps one filter control: hides it when it changes no insight, and says in a tooltip how many insights it changes. */
function DashboardControlSlot({
    control,
    hasValue,
    className,
    children,
}: {
    control: DashboardControl
    hasValue: boolean
    className?: string
    children: ReactNode
}): JSX.Element | null {
    const { dashboardControlScopes } = useValues(dashboardLogic)
    const controlsEnabled = useFeatureFlag('METRICS_DASHBOARD_CONTROLS')

    if (!controlsEnabled) {
        return <div className={className}>{children}</div>
    }
    const scope = dashboardControlScopes[control]
    if (isDashboardControlHidden(scope, hasValue)) {
        return null
    }
    const scopeText = dashboardControlScopeText(scope)
    return (
        <Tooltip title={scopeText} placement="top" delayMs={300}>
            <div className={className}>{children}</div>
        </Tooltip>
    )
}

export function DashboardIntervalFilter(): JSX.Element {
    const { dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setInterval, setDashboardEditing } = useActions(dashboardLogic)

    return (
        <span className="flex items-center gap-2">
            <span className="hidden md:inline">grouped by</span>
            <LemonSelect<IntervalType | null>
                size="small"
                value={effectiveEditBarFilters.interval ?? null}
                dropdownMatchSelectWidth={false}
                onChange={(interval) => {
                    if (!dashboardEditing?.filters) {
                        setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
                    }
                    setInterval(interval)
                }}
                options={[
                    { value: null, label: "each insight's interval" },
                    { value: 'hour', label: 'hour' },
                    { value: 'day', label: 'day' },
                    { value: 'week', label: 'week' },
                    { value: 'month', label: 'month' },
                ]}
            />
        </span>
    )
}

export function DashboardEditBar({ showDateFilter = true, className }: DashboardEditBarProps): JSX.Element {
    const {
        dashboard,
        dashboardEditing,
        hasVariables,
        effectiveEditBarFilters,
        dashboardControlScopes,
        canEditDashboard,
        placement,
    } = useValues(dashboardLogic)
    const hasDashboardColors = useFeatureFlag('PRODUCT_ANALYTICS_DASHBOARD_COLORS')
    const { setDates, setProperties, setBreakdownFilter, setDashboardEditing, setInterval } = useActions(dashboardLogic)
    const controlsEnabled = useFeatureFlag('METRICS_DASHBOARD_CONTROLS')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const { hasPageview, hasScreen } = getProjectEventExistence()

    const hasDateRange = !!effectiveEditBarFilters.date_from || !!effectiveEditBarFilters.date_to
    const dateRangeHidden = controlsEnabled && isDashboardControlHidden(dashboardControlScopes.dateRange, hasDateRange)

    const hasInterval = effectiveEditBarFilters.interval != null
    const intervalHidden = controlsEnabled && isDashboardControlHidden(dashboardControlScopes.interval, hasInterval)

    const testAccountsHidden =
        controlsEnabled &&
        isDashboardControlHidden(
            dashboardControlScopes.testAccounts,
            effectiveEditBarFilters.filterTestAccounts != null
        )
    // Only the full dashboard scene mounts DashboardInsightColorsModal, so elsewhere the row would do nothing.
    const showColors =
        hasDashboardColors && canEditDashboard && !!dashboard && placement === DashboardPlacement.Dashboard
    const { showInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)

    const hasBreakdown = !!effectiveEditBarFilters.breakdown_filter
    const breakdownHidden = controlsEnabled && isDashboardControlHidden(dashboardControlScopes.breakdown, hasBreakdown)

    const onBreakdownChange = (breakdownFilter: BreakdownFilter | null): void => {
        if (!dashboardEditing?.filters) {
            setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
        }
        setBreakdownFilter(breakdownFilter)
    }

    const onDatesChange = (dateFrom: string | null, dateTo: string | null, explicitDate?: boolean): void => {
        if (!dashboardEditing?.filters) {
            setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
        }
        setDates(dateFrom, dateTo, explicitDate)
    }

    const onPropertiesChange = (properties: AnyPropertyFilter[]): void => {
        if (!dashboardEditing?.filters) {
            setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
        }
        setProperties(properties)
    }

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
        <div
            className={
                className ??
                clsx(
                    'flex gap-2 items-end flex-wrap border',
                    todayRailNav && 'min-w-0 flex-1',
                    dashboardEditing?.filters
                        ? '-m-1.5 p-1.5 border-primary border-dashed rounded-lg'
                        : 'border-transparent'
                )
            }
        >
            {showDateFilter && !todayRailNav && (
                <DashboardControlSlot
                    control="dateRange"
                    hasValue={hasDateRange}
                    className={clsx('content-end min-w-0', { 'h-[61px]': hasVariables })}
                >
                    <Shortcut
                        name="DashboardDateFilter"
                        keybind={[keyBinds.dateFilter]}
                        intent="Date filter"
                        interaction="click"
                        scope={Scene.Dashboard}
                    >
                        <DateFilter
                            showCustom
                            showExplicitDateToggle
                            allowTimePrecision
                            allowFixedRangeWithTime
                            dateFrom={effectiveEditBarFilters.date_from}
                            dateTo={effectiveEditBarFilters.date_to}
                            explicitDate={effectiveEditBarFilters.explicitDate}
                            onChange={onDatesChange}
                            makeLabel={(key) => (
                                <>
                                    <IconCalendar />
                                    <span className="hide-when-small"> {key}</span>
                                </>
                            )}
                        />
                    </Shortcut>
                </DashboardControlSlot>
            )}
            {showDateFilter && !todayRailNav && (
                <DashboardControlSlot
                    control="interval"
                    hasValue={hasInterval}
                    className={clsx('content-end', { 'h-[61px]': hasVariables })}
                >
                    <DashboardIntervalFilter />
                </DashboardControlSlot>
            )}
            {todayRailNav ? (
                <div className={clsx('min-w-0 flex-1 content-end', { 'h-[61px]': hasVariables })}>
                    <FilterBar
                        pageKey={'dashboard_' + dashboard?.id}
                        filters={effectiveEditBarFilters.properties ?? []}
                        onChange={onPropertiesChange}
                        trailing={
                            <>
                                {!breakdownHidden && (
                                    <FilterBarBreakdown
                                        breakdownFilter={effectiveEditBarFilters.breakdown_filter}
                                        onChange={onBreakdownChange}
                                    />
                                )}
                            </>
                        }
                        actions={<DashboardUnsavedChangesMenu />}
                    >
                        {showDateFilter && !dateRangeHidden && (
                            <FilterBarDateRange
                                dateFrom={effectiveEditBarFilters.date_from}
                                dateTo={effectiveEditBarFilters.date_to}
                                onChange={(dateFrom, dateTo) =>
                                    onDatesChange(dateFrom, dateTo, effectiveEditBarFilters.explicitDate ?? undefined)
                                }
                            />
                        )}
                        {showDateFilter && !intervalHidden && (
                            <FilterBarInterval
                                value={effectiveEditBarFilters.interval}
                                defaultLabel="Each insight's interval"
                                onChange={(interval) => {
                                    if (!dashboardEditing?.filters) {
                                        setDashboardEditing(
                                            { filters: true, layout: false },
                                            DashboardEventSource.DashboardFilters
                                        )
                                    }
                                    setInterval(interval)
                                }}
                            />
                        )}
                        {!testAccountsHidden && <DashboardTestAccountsControl />}
                        {showDateFilter && <DashboardComparisonControl />}
                        {showColors && (
                            <FilterBarAction
                                id="breakdown-colors"
                                label="Customize breakdown colors"
                                icon={IconPalette}
                                onSelect={() => dashboard && showInsightColorsModal(dashboard.id)}
                            />
                        )}
                    </FilterBar>
                </div>
            ) : (
                <DashboardControlSlot
                    control="properties"
                    hasValue={(effectiveEditBarFilters.properties?.length ?? 0) > 0}
                    className={clsx('content-end', { 'h-[61px]': hasVariables })}
                >
                    <PropertyFilters
                        onChange={onPropertiesChange}
                        pageKey={'dashboard_' + dashboard?.id}
                        propertyFilters={effectiveEditBarFilters.properties}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.EventFeatureFlags,
                            TaxonomicFilterGroupType.EventMetadata,
                            ...(hasPageview ? [TaxonomicFilterGroupType.PageviewUrls] : []),
                            ...(hasScreen ? [TaxonomicFilterGroupType.Screens] : []),
                            TaxonomicFilterGroupType.EmailAddresses,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.Elements,
                            TaxonomicFilterGroupType.SessionProperties,
                            TaxonomicFilterGroupType.HogQLExpression,
                            TaxonomicFilterGroupType.DataWarehousePersonProperties,
                        ]}
                    />
                </DashboardControlSlot>
            )}
            {!todayRailNav && (
                <DashboardControlSlot
                    control="breakdown"
                    hasValue={hasBreakdown}
                    className={clsx('content-end', { 'h-[61px]': hasVariables })}
                >
                    <BindLogic logic={insightLogic} props={insightProps}>
                        <TaxonomicBreakdownFilter
                            insightProps={insightProps}
                            breakdownFilter={effectiveEditBarFilters.breakdown_filter}
                            isTrends={false}
                            isFunnels={false}
                            showLabel={false}
                            updateBreakdownFilter={(breakdown_filter) => {
                                let saved_breakdown_filter: BreakdownFilter | null = breakdown_filter
                                // taxonomicBreakdownFilterLogic can generate an empty breakdown_filter object
                                if (
                                    breakdown_filter &&
                                    !breakdown_filter.breakdown_type &&
                                    !breakdown_filter.breakdowns
                                ) {
                                    saved_breakdown_filter = null
                                }
                                onBreakdownChange(saved_breakdown_filter)
                            }}
                            updateDisplay={() => {}}
                            disablePropertyInfo
                            size="small"
                        />
                    </BindLogic>
                </DashboardControlSlot>
            )}

            <VariablesForDashboard />
            {!todayRailNav && (
                <div className={clsx('content-end', { 'h-[61px]': hasVariables })}>
                    <DashboardEditBarAdvancedFilters showCompareFilter={showDateFilter} />
                </div>
            )}
            {controlsEnabled && (
                <DashboardControlSlot
                    control="metricVariables"
                    hasValue={(effectiveEditBarFilters.metricVariables?.length ?? 0) > 0}
                    className={clsx('content-end', { 'h-[61px]': hasVariables })}
                >
                    <div className="flex min-h-[30px] flex-wrap items-end gap-1 border-l border-primary pl-2">
                        <DashboardMetricVariables />
                    </div>
                </DashboardControlSlot>
            )}
        </div>
    )
}
