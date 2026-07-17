import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'

import { IconCalendar, IconCollapse, IconExpand, IconGear } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { VariablesForDashboard } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { BreakdownFilter, NodeKind } from '~/queries/schema/schema-general'
import { DashboardMode, InsightLogicProps, IntervalType } from '~/types'

interface DashboardEditBarProps {
    showDateFilter?: boolean
    className?: string
}

export function DashboardIntervalFilter(): JSX.Element {
    const { dashboardMode, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setInterval, setDashboardMode } = useActions(dashboardLogic)

    return (
        <span className="flex items-center gap-2">
            <span className="hidden md:inline">grouped by</span>
            <LemonSelect<IntervalType | null>
                size="small"
                value={effectiveEditBarFilters.interval ?? null}
                dropdownMatchSelectWidth={false}
                onChange={(interval) => {
                    if (dashboardMode !== DashboardMode.Edit) {
                        setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
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

export function DashboardTestAccountFilter(): JSX.Element {
    const { dashboardMode, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setFilterTestAccounts, setDashboardMode } = useActions(dashboardLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    return (
        <span className="flex items-center gap-2">
            <span>internal and test users</span>
            <LemonSelect<boolean | null>
                size="small"
                value={effectiveEditBarFilters.filterTestAccounts ?? null}
                dropdownMatchSelectWidth={false}
                disabledReason={
                    !hasFilters
                        ? "You haven't set any internal test filters. Click the gear icon to configure."
                        : undefined
                }
                onChange={(filterTestAccounts) => {
                    if (dashboardMode !== DashboardMode.Edit) {
                        setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
                    }
                    setFilterTestAccounts(filterTestAccounts)
                }}
                options={[
                    { value: null, label: "each insight's setting" },
                    { value: true, label: 'excluded' },
                    { value: false, label: 'included' },
                ]}
            />
            <LemonButton
                icon={<IconGear />}
                size="small"
                noPadding
                to={urls.settings('project-product-analytics', 'internal-user-filtering')}
            />
        </span>
    )
}

export function DashboardEditBar({ showDateFilter = true, className }: DashboardEditBarProps): JSX.Element {
    const {
        dashboard,
        dashboardMode,
        hasVariables,
        effectiveEditBarFilters,
        showAdvancedOverrides,
        advancedOverridesCount,
    } = useValues(dashboardLogic)
    const { setDates, setProperties, setBreakdownFilter, setDashboardMode, toggleAdvancedOverrides } =
        useActions(dashboardLogic)
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
                    'flex flex-col gap-2 border',
                    dashboardMode === DashboardMode.Edit
                        ? '-m-1.5 p-1.5 border-primary border-dashed rounded-lg'
                        : 'border-transparent'
                )
            }
        >
            <div className="flex gap-2 items-end flex-wrap">
                {showDateFilter && (
                    <div className={clsx('content-end min-w-0', { 'h-[61px]': hasVariables })}>
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
                                    if (dashboardMode !== DashboardMode.Edit) {
                                        setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
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
                    </div>
                )}
                {showDateFilter && (
                    <div className={clsx('content-end', { 'h-[61px]': hasVariables })}>
                        <DashboardIntervalFilter />
                    </div>
                )}
                <div className={clsx('content-end', { 'h-[61px]': hasVariables })}>
                    <LemonButton
                        size="small"
                        data-attr="dashboard-advanced-overrides-toggle"
                        onClick={toggleAdvancedOverrides}
                        sideIcon={showAdvancedOverrides ? <IconCollapse /> : <IconExpand />}
                    >
                        Advanced overrides
                        {advancedOverridesCount > 0 && (
                            <span className="ml-1 text-muted">({advancedOverridesCount})</span>
                        )}
                    </LemonButton>
                </div>

                <VariablesForDashboard />
            </div>
            {showAdvancedOverrides && (
                <div className="flex gap-2 items-end flex-wrap">
                    <div className="content-end min-w-0">
                        <PropertyFilters
                            onChange={(properties) => {
                                if (dashboardMode !== DashboardMode.Edit) {
                                    setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
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
                    </div>
                    <div className="content-end">
                        <BindLogic logic={insightLogic} props={insightProps}>
                            <TaxonomicBreakdownFilter
                                insightProps={insightProps}
                                breakdownFilter={effectiveEditBarFilters.breakdown_filter}
                                isTrends={false}
                                isFunnels={false}
                                showLabel={false}
                                updateBreakdownFilter={(breakdown_filter) => {
                                    if (dashboardMode !== DashboardMode.Edit) {
                                        setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
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
                    <div className="content-end">
                        <DashboardTestAccountFilter />
                    </div>
                </div>
            )}
        </div>
    )
}
