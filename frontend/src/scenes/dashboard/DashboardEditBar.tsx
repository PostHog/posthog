import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconCalendar, IconLive } from '@posthog/icons'
import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
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
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Scene } from 'scenes/sceneTypes'

import { groupsModel } from '~/models/groupsModel'
import { VariablesForDashboard } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { BreakdownFilter, NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps, IntervalType } from '~/types'

import { DashboardMetricLabelFilter } from 'products/metrics/frontend/components/DashboardMetricLabelFilter'

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
    const { dashboard, dashboardEditing, hasVariables, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setDates, setProperties, setBreakdownFilter, setMetricFilters, setDashboardEditing } =
        useActions(dashboardLogic)
    const controlsEnabled = useFeatureFlag('METRICS_DASHBOARD_CONTROLS')
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const { hasPageview, hasScreen } = getProjectEventExistence()

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
                    dashboardEditing?.filters
                        ? '-m-1.5 p-1.5 border-primary border-dashed rounded-lg'
                        : 'border-transparent'
                )
            }
        >
            {showDateFilter && (
                <DashboardControlSlot
                    control="dateRange"
                    hasValue={!!effectiveEditBarFilters.date_from || !!effectiveEditBarFilters.date_to}
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
                            onChange={(from_date, to_date, explicitDate) => {
                                if (!dashboardEditing?.filters) {
                                    setDashboardEditing(
                                        { filters: true, layout: false },
                                        DashboardEventSource.DashboardFilters
                                    )
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
                    </Shortcut>
                </DashboardControlSlot>
            )}
            {showDateFilter && (
                <DashboardControlSlot
                    control="interval"
                    hasValue={effectiveEditBarFilters.interval != null}
                    className={clsx('content-end', { 'h-[61px]': hasVariables })}
                >
                    <DashboardIntervalFilter />
                </DashboardControlSlot>
            )}
            <DashboardControlSlot
                control="properties"
                hasValue={(effectiveEditBarFilters.properties?.length ?? 0) > 0}
                className={clsx('content-end', { 'h-[61px]': hasVariables })}
            >
                <PropertyFilters
                    onChange={(properties) => {
                        if (!dashboardEditing?.filters) {
                            setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
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
            <DashboardControlSlot
                control="breakdown"
                hasValue={!!effectiveEditBarFilters.breakdown_filter}
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
                            if (!dashboardEditing?.filters) {
                                setDashboardEditing(
                                    { filters: true, layout: false },
                                    DashboardEventSource.DashboardFilters
                                )
                            }
                            let saved_breakdown_filter: BreakdownFilter | null = breakdown_filter
                            // taxonomicBreakdownFilterLogic can generate an empty breakdown_filter object
                            if (breakdown_filter && !breakdown_filter.breakdown_type && !breakdown_filter.breakdowns) {
                                saved_breakdown_filter = null
                            }
                            setBreakdownFilter(saved_breakdown_filter)
                        }}
                        updateDisplay={() => {}}
                        disablePropertyInfo
                        size="small"
                    />
                </BindLogic>
            </DashboardControlSlot>

            <VariablesForDashboard />
            <div className={clsx('content-end', { 'h-[61px]': hasVariables })}>
                <DashboardEditBarAdvancedFilters />
            </div>
            {controlsEnabled && (
                <DashboardControlSlot
                    control="metricLabels"
                    hasValue={(effectiveEditBarFilters.metricFilters?.length ?? 0) > 0}
                    className={clsx('content-end', { 'h-[61px]': hasVariables })}
                >
                    <div className="flex min-h-[30px] flex-wrap items-center gap-1 border-l border-primary pl-2">
                        <span className="flex items-center gap-1 text-xs font-semibold text-secondary">
                            <IconLive className="text-sm" />
                            Metrics
                        </span>
                        <DashboardMetricLabelFilter
                            metricFilters={effectiveEditBarFilters.metricFilters}
                            onChange={(metricFilters) => {
                                if (!dashboardEditing?.filters) {
                                    setDashboardEditing(
                                        { filters: true, layout: false },
                                        DashboardEventSource.DashboardFilters
                                    )
                                }
                                setMetricFilters(metricFilters)
                            }}
                        />
                    </div>
                </DashboardControlSlot>
            )}
        </div>
    )
}
