import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconCalendar } from '@posthog/icons'
import { LemonSelect, Tooltip } from '@posthog/lemon-ui'
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { QuillSurfaceContext, useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Scene } from 'scenes/sceneTypes'

import { groupsModel } from '~/models/groupsModel'
import { VariablesForDashboard } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { BreakdownFilter, NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps, IntervalType } from '~/types'

import { DashboardMetricVariables } from 'products/metrics/frontend/components/dashboardVariables/DashboardMetricVariables'
import { TaxonomicBreakdownFilter } from 'products/product_analytics/frontend/insights/editor/filters/BreakdownFilter/TaxonomicBreakdownFilter'

import { DashboardControl, dashboardControlScopeText, isDashboardControlHidden } from './dashboardControls'
import { DashboardEditBarAdvancedFilters } from './DashboardEditBarAdvancedFilters'

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

const GROUP_BY_INTERVAL_OPTIONS: { value: IntervalType | null; label: string }[] = [
    { value: null, label: "each insight's interval" },
    { value: 'hour', label: 'hour' },
    { value: 'day', label: 'day' },
    { value: 'week', label: 'week' },
    { value: 'month', label: 'month' },
]

// Quill's Select can't hold null as an item value, so "no override" gets its own key.
const NO_INTERVAL_OVERRIDE = 'inherit' as const

export function DashboardIntervalFilter(): JSX.Element {
    const { dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setInterval, setDashboardEditing } = useActions(dashboardLogic)
    const quillSurface = useQuillSurface()

    const onChange = (interval: IntervalType | null): void => {
        if (!dashboardEditing?.filters) {
            setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
        }
        setInterval(interval)
    }

    return (
        <span className="flex items-center gap-2">
            <span className="hidden md:inline">grouped by</span>
            {quillSurface ? (
                <Select<IntervalType | typeof NO_INTERVAL_OVERRIDE>
                    value={effectiveEditBarFilters.interval ?? NO_INTERVAL_OVERRIDE}
                    onValueChange={(value) => onChange(!value || value === NO_INTERVAL_OVERRIDE ? null : value)}
                >
                    <SelectTrigger render={<Button variant="outline" left />} data-attr="dashboard-interval-filter">
                        <SelectValue>
                            {(value: IntervalType | typeof NO_INTERVAL_OVERRIDE) =>
                                GROUP_BY_INTERVAL_OPTIONS.find(
                                    (option) => (option.value ?? NO_INTERVAL_OVERRIDE) === value
                                )?.label ?? value
                            }
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent align="start" alignItemWithTrigger={false}>
                        {GROUP_BY_INTERVAL_OPTIONS.map((option) => (
                            <SelectItem
                                key={option.value ?? NO_INTERVAL_OVERRIDE}
                                value={option.value ?? NO_INTERVAL_OVERRIDE}
                            >
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            ) : (
                <LemonSelect<IntervalType | null>
                    size="small"
                    value={effectiveEditBarFilters.interval ?? null}
                    dropdownMatchSelectWidth={false}
                    onChange={onChange}
                    options={GROUP_BY_INTERVAL_OPTIONS}
                />
            )}
        </span>
    )
}

export function DashboardEditBar({ showDateFilter = true, className }: DashboardEditBarProps): JSX.Element {
    const { dashboard, dashboardEditing, hasVariables, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setDates, setProperties, setBreakdownFilter, setDashboardEditing } = useActions(dashboardLogic)
    const controlsEnabled = useFeatureFlag('METRICS_DASHBOARD_CONTROLS')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
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
        // The property filter and breakdown pickers are shared with unmigrated screens, so they switch to quill
        // only inside this provider.
        <QuillSurfaceContext.Provider value={todayRailNav}>
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
                                setDashboardEditing(
                                    { filters: true, layout: false },
                                    DashboardEventSource.DashboardFilters
                                )
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
                </DashboardControlSlot>

                <VariablesForDashboard />
                <div className={clsx('content-end', { 'h-[61px]': hasVariables })}>
                    <DashboardEditBarAdvancedFilters showCompareFilter={showDateFilter} />
                </div>
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
        </QuillSurfaceContext.Provider>
    )
}
