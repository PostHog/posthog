import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter, IconGear, IconPalette } from '@posthog/icons'
import {
    Badge,
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    FieldSeparator,
    Heading,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { getDashboardActiveFilters, normalizeDashboardBreakdownFilter } from 'scenes/dashboard/dashboardActiveFilters'
import {
    DashboardControl,
    dashboardControlScopeText,
    isDashboardControlHidden,
} from 'scenes/dashboard/dashboardControls'
import { dashboardInsightColorsModalLogic } from 'scenes/dashboard/dashboardInsightColorsModalLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardPropertyFilterGroupTypes } from 'scenes/dashboard/dashboardPropertyFilterGroupTypes'
import {
    TEST_ACCOUNT_CHOICE_HINTS,
    TEST_ACCOUNT_CHOICE_TO_FILTER,
    TestAccountFilterChoice,
    testAccountFilterChoice,
} from 'scenes/dashboard/dashboardTestAccountFilterChoice'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { DashboardPlacement, InsightLogicProps, IntervalType } from '~/types'

import { DashboardCompareFilter } from 'products/dashboards/frontend/components/DashboardCompareFilter/DashboardCompareFilter'
import { DashboardMetricVariables } from 'products/metrics/frontend/components/dashboardVariables/DashboardMetricVariables'

const INHERIT_INTERVAL = 'inherit'
type IntervalChoice = IntervalType | typeof INHERIT_INTERVAL

const INTERVAL_ITEMS: { value: IntervalChoice; label: string }[] = [
    { value: INHERIT_INTERVAL, label: "Each insight's interval" },
    { value: 'hour', label: 'Hour' },
    { value: 'day', label: 'Day' },
    { value: 'week', label: 'Week' },
    { value: 'month', label: 'Month' },
]

const TEST_ACCOUNT_ITEMS: { value: TestAccountFilterChoice; label: string; dataAttr: string }[] = [
    { value: 'inherit', label: 'Inherit', dataAttr: 'dashboard-test-account-filter-inherit' },
    { value: 'filter-out', label: 'Filter out', dataAttr: 'dashboard-test-account-filter-out' },
    { value: 'include', label: 'Include', dataAttr: 'dashboard-test-account-filter-include' },
]

/**
 * The property and breakdown pickers are LemonUI and open their own popovers in a portal outside this one.
 * A press or a focus move into such a popover must not close this popover.
 */
function isInLemonOverlay(target: EventTarget | null | undefined): boolean {
    return target instanceof Element && !!target.closest('.Popover, .LemonModal__container')
}

/**
 * The "Filters" control of the dashboard filter bar. It keeps the overrides that change less often than the
 * date range (properties, breakdown, interval, test accounts, comparison) in one popover. A count badge says
 * how many are in force.
 */
export function QuillDashboardFiltersPopover(): JSX.Element {
    const {
        dashboard,
        dashboardEditing,
        effectiveEditBarFilters,
        dashboardControlScopes,
        canEditDashboard,
        placement,
    } = useValues(dashboardLogic)
    const { setProperties, setBreakdownFilter, setInterval, setFilterTestAccounts, setDashboardEditing } =
        useActions(dashboardLogic)
    const { showInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { currentTeam } = useValues(teamLogic)
    const controlsEnabled = useFeatureFlag('METRICS_DASHBOARD_CONTROLS')
    const hasDashboardColors = useFeatureFlag('PRODUCT_ANALYTICS_DASHBOARD_COLORS')
    const [open, setOpen] = useState(false)

    const activeCount = getDashboardActiveFilters(effectiveEditBarFilters).length
    const testAccountChoice = testAccountFilterChoice(effectiveEditBarFilters.filterTestAccounts)
    const hasTestAccountFilters = (currentTeam?.test_account_filters || []).length > 0
    // Only the full dashboard scene mounts DashboardInsightColorsModal, so elsewhere the button would no-op.
    const showColors =
        hasDashboardColors && canEditDashboard && !!dashboard && placement === DashboardPlacement.Dashboard

    const startFiltersEditing = (): void => {
        if (!dashboardEditing?.filters) {
            setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
        }
    }
    const isHidden = (control: DashboardControl, hasValue: boolean): boolean =>
        controlsEnabled && isDashboardControlHidden(dashboardControlScopes[control], hasValue)
    const scopeText = (control: DashboardControl): string | null =>
        controlsEnabled ? dashboardControlScopeText(dashboardControlScopes[control]) : null

    const breakdownInsightProps: InsightLogicProps = {
        dashboardItemId: 'new',
        dashboardId: dashboard?.id,
        cachedInsight: null,
        query: { kind: NodeKind.InsightVizNode, source: { kind: NodeKind.TrendsQuery, series: [] } },
    }

    const sections: { key: string; content: JSX.Element }[] = []
    if (!isHidden('properties', (effectiveEditBarFilters.properties?.length ?? 0) > 0)) {
        sections.push({
            key: 'properties',
            content: (
                <Field>
                    <FieldLabel>Properties</FieldLabel>
                    <PropertyFilters
                        onChange={(properties) => {
                            startFiltersEditing()
                            setProperties(properties)
                        }}
                        pageKey={'dashboard_' + dashboard?.id}
                        propertyFilters={effectiveEditBarFilters.properties}
                        taxonomicGroupTypes={dashboardPropertyFilterGroupTypes(groupsTaxonomicTypes)}
                    />
                    {scopeText('properties') && <FieldDescription>{scopeText('properties')}</FieldDescription>}
                </Field>
            ),
        })
    }
    if (!isHidden('breakdown', !!effectiveEditBarFilters.breakdown_filter)) {
        sections.push({
            key: 'breakdown',
            content: (
                <Field>
                    <FieldLabel>Breakdown</FieldLabel>
                    <BindLogic logic={insightLogic} props={breakdownInsightProps}>
                        <TaxonomicBreakdownFilter
                            insightProps={breakdownInsightProps}
                            breakdownFilter={effectiveEditBarFilters.breakdown_filter}
                            isTrends={false}
                            isFunnels={false}
                            showLabel={false}
                            updateBreakdownFilter={(breakdownFilter) => {
                                startFiltersEditing()
                                setBreakdownFilter(normalizeDashboardBreakdownFilter(breakdownFilter))
                            }}
                            updateDisplay={() => {}}
                            disablePropertyInfo
                            size="small"
                        />
                    </BindLogic>
                    {scopeText('breakdown') && <FieldDescription>{scopeText('breakdown')}</FieldDescription>}
                </Field>
            ),
        })
    }
    if (!isHidden('interval', effectiveEditBarFilters.interval != null)) {
        sections.push({
            key: 'interval',
            content: (
                <Field>
                    <FieldLabel>Grouped by</FieldLabel>
                    <Select<IntervalChoice>
                        items={INTERVAL_ITEMS}
                        value={effectiveEditBarFilters.interval ?? INHERIT_INTERVAL}
                        onValueChange={(next) => {
                            startFiltersEditing()
                            setInterval(next === INHERIT_INTERVAL || next == null ? null : next)
                        }}
                    >
                        <SelectTrigger data-attr="dashboard-interval-filter">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {INTERVAL_ITEMS.map(({ value, label }) => (
                                <SelectItem key={value} value={value}>
                                    {label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    {scopeText('interval') && <FieldDescription>{scopeText('interval')}</FieldDescription>}
                </Field>
            ),
        })
    }
    sections.push({
        key: 'testAccounts',
        content: (
            <Field>
                <div className="flex items-center justify-between gap-1">
                    <FieldLabel>Test account filtering</FieldLabel>
                    <Button
                        size="icon-sm"
                        aria-label="Configure internal and test account filters"
                        tooltip="Configure internal and test account filters"
                        render={
                            <LinkPrimitive to={urls.settings('project-product-analytics', 'internal-user-filtering')} />
                        }
                    >
                        <IconGear />
                    </Button>
                </div>
                <ToggleGroup
                    className="w-full"
                    value={[testAccountChoice]}
                    onValueChange={(next) => {
                        // A press on the pressed item clears the group. The choice stays as it was.
                        const nextChoice = next[0] as TestAccountFilterChoice | undefined
                        if (!nextChoice) {
                            return
                        }
                        startFiltersEditing()
                        setFilterTestAccounts(TEST_ACCOUNT_CHOICE_TO_FILTER[nextChoice])
                    }}
                >
                    {TEST_ACCOUNT_ITEMS.map(({ value, label, dataAttr }) => (
                        <ToggleGroupItem
                            key={value}
                            value={value}
                            className="flex-1"
                            data-attr={dataAttr}
                            disabledReason={
                                value === 'filter-out' && !hasTestAccountFilters
                                    ? "You haven't set any internal test filters. Use the gear button to configure them."
                                    : undefined
                            }
                        >
                            {label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
                <FieldDescription>{TEST_ACCOUNT_CHOICE_HINTS[testAccountChoice]}</FieldDescription>
                {scopeText('testAccounts') && <FieldDescription>{scopeText('testAccounts')}</FieldDescription>}
            </Field>
        ),
    })
    sections.push({
        key: 'compare',
        content: (
            <Field>
                <FieldLabel>Comparison</FieldLabel>
                <DashboardCompareFilter fullWidth />
            </Field>
        ),
    })
    if (controlsEnabled && !isHidden('metricVariables', (effectiveEditBarFilters.metricVariables?.length ?? 0) > 0)) {
        sections.push({
            key: 'metricVariables',
            content: (
                <Field>
                    <FieldLabel>Metric variables</FieldLabel>
                    <div className="flex flex-wrap items-end gap-1">
                        <DashboardMetricVariables />
                    </div>
                </Field>
            ),
        })
    }
    if (showColors) {
        sections.push({
            key: 'colors',
            content: (
                <Field>
                    <FieldLabel>Breakdown colors</FieldLabel>
                    <Button
                        variant="outline"
                        onClick={() => {
                            setOpen(false)
                            showInsightColorsModal(dashboard.id)
                        }}
                        data-attr="dashboard-advanced-customize-colors"
                    >
                        <IconPalette />
                        Customize colors
                    </Button>
                </Field>
            ),
        })
    }

    return (
        <Popover
            open={open}
            onOpenChange={(nextOpen, details) => {
                if (
                    !nextOpen &&
                    (details.reason === 'outside-press' || details.reason === 'focus-out') &&
                    (isInLemonOverlay(details.event?.target) ||
                        isInLemonOverlay((details.event as FocusEvent | undefined)?.relatedTarget))
                ) {
                    return
                }
                setOpen(nextOpen)
            }}
        >
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        aria-label={activeCount ? `Filters, ${activeCount} active` : 'Filters'}
                        data-attr="dashboard-filters-popover"
                    />
                }
            >
                <IconFilter />
                Filters
                {activeCount > 0 && <Badge variant="info">{activeCount}</Badge>}
            </PopoverTrigger>
            <PopoverContent align="start" className="w-96 max-w-(--available-width) gap-3">
                <div className="flex flex-col gap-1">
                    <Heading size="sm" render={<h4 className="m-0" />}>
                        Filters
                    </Heading>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Overrides applied to every insight on this dashboard.
                    </Text>
                </div>
                {sections.map(({ key, content }, index) => (
                    <div key={key} className="flex flex-col gap-3">
                        {index > 0 && <FieldSeparator />}
                        {content}
                    </div>
                ))}
            </PopoverContent>
        </Popover>
    )
}
