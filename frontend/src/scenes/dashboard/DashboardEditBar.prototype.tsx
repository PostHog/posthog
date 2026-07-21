/**
 * PROTOTYPE — throwaway. Radically different layouts of the dashboard edit bar,
 * switchable via `?variant=A|B|C|D|E|F` on the real dashboard route. Flip between
 * them with the floating bottom bar (dev builds only). Delete this file and the
 * `?variant` gate in DashboardEditBar.tsx once a direction is picked.
 *
 * Business logic intentionally lives in local component state here (not kea) —
 * this is a disposable design spike, not production code.
 */
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import {
    IconCalendar,
    IconChevronLeft,
    IconChevronRight,
    IconClock,
    IconCollapse,
    IconDirectedGraph,
    IconExpand,
    IconFilter,
    IconGear,
    IconPerson,
    IconPlus,
} from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonLabel, LemonSelect, LemonSnack } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { VariablesForDashboard } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { BreakdownFilter, NodeKind } from '~/queries/schema/schema-general'
import { DashboardMode, InsightLogicProps } from '~/types'

export const PROTOTYPE_VARIANTS = ['A', 'B', 'C', 'D', 'E', 'F'] as const
export type PrototypeVariant = (typeof PROTOTYPE_VARIANTS)[number]

const VARIANT_NAMES: Record<PrototypeVariant, string> = {
    A: 'Compact popover toolbar',
    B: 'Labeled field grid',
    C: 'Chip summary bar',
    D: 'Current top bar + labeled panel',
    E: 'Filters inline + separate variables bar',
    F: 'Filters inline, no advanced background',
}

// A single place to reach the dashboard filter state + ensure we're in edit mode.
function useEditModel(): {
    filters: ReturnType<typeof useValues<typeof dashboardLogic>>['effectiveEditBarFilters']
    hasTestFilters: boolean
    hasPageview: boolean
    hasScreen: boolean
    groupsTaxonomicTypes: TaxonomicFilterGroupType[]
    dashboardId: number | undefined
    ensureEdit: () => void
    setDates: (from: string | null, to: string | null, explicit?: boolean) => void
    setInterval: (interval: string | null) => void
    setFilterTestAccounts: (value: boolean | null) => void
    setProperties: (properties: any[]) => void
    setBreakdownFilter: (breakdown: BreakdownFilter | null) => void
} {
    const { dashboard, dashboardMode, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setDates, setInterval, setFilterTestAccounts, setProperties, setBreakdownFilter, setDashboardMode } =
        useActions(dashboardLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { currentTeam } = useValues(teamLogic)
    const { hasPageview, hasScreen } = getProjectEventExistence()

    const ensureEdit = (): void => {
        if (dashboardMode !== DashboardMode.Edit) {
            setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardFilters)
        }
    }

    return {
        filters: effectiveEditBarFilters,
        hasTestFilters: (currentTeam?.test_account_filters || []).length > 0,
        hasPageview,
        hasScreen,
        groupsTaxonomicTypes,
        dashboardId: dashboard?.id,
        ensureEdit,
        setDates: (from, to, explicit) => {
            ensureEdit()
            setDates(from, to, explicit)
        },
        setInterval: (interval) => {
            ensureEdit()
            setInterval(interval as any)
        },
        setFilterTestAccounts: (value) => {
            ensureEdit()
            setFilterTestAccounts(value)
        },
        setProperties: (properties) => {
            ensureEdit()
            setProperties(properties)
        },
        setBreakdownFilter: (breakdown) => {
            ensureEdit()
            setBreakdownFilter(breakdown)
        },
    }
}

// ----- Raw controls, reused across variants -----

function DateControl(): JSX.Element {
    const m = useEditModel()
    return (
        <DateFilter
            showCustom
            showExplicitDateToggle
            allowTimePrecision
            allowFixedRangeWithTime
            dateFrom={m.filters.date_from}
            dateTo={m.filters.date_to}
            explicitDate={m.filters.explicitDate}
            onChange={(from, to, explicit) => m.setDates(from, to, explicit)}
            makeLabel={(key) => (
                <>
                    <IconCalendar /> <span>{key}</span>
                </>
            )}
        />
    )
}

function IntervalControl(): JSX.Element {
    const m = useEditModel()
    return (
        <LemonSelect
            size="small"
            value={m.filters.interval ?? null}
            dropdownMatchSelectWidth={false}
            onChange={(interval) => m.setInterval(interval)}
            options={[
                { value: null, label: "each insight's interval" },
                { value: 'hour', label: 'hour' },
                { value: 'day', label: 'day' },
                { value: 'week', label: 'week' },
                { value: 'month', label: 'month' },
            ]}
        />
    )
}

function TestUsersControl(): JSX.Element {
    const m = useEditModel()
    return (
        <LemonSelect<boolean | null>
            size="small"
            value={m.filters.filterTestAccounts ?? null}
            dropdownMatchSelectWidth={false}
            disabledReason={
                !m.hasTestFilters
                    ? "You haven't set any internal test filters. Use the settings gear to configure."
                    : undefined
            }
            onChange={(value) => m.setFilterTestAccounts(value)}
            options={[
                { value: null, label: "Each insight's setting for internal and test users" },
                { value: true, label: 'Internal and test users excluded' },
                { value: false, label: 'Internal and test users included' },
            ]}
        />
    )
}

function BreakdownControl(): JSX.Element {
    const m = useEditModel()
    const insightProps: InsightLogicProps = {
        dashboardItemId: 'new',
        dashboardId: m.dashboardId,
        cachedInsight: null,
        query: { kind: NodeKind.InsightVizNode, source: { kind: NodeKind.TrendsQuery, series: [] } },
    }
    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <TaxonomicBreakdownFilter
                insightProps={insightProps}
                breakdownFilter={m.filters.breakdown_filter}
                isTrends={false}
                isFunnels={false}
                showLabel={false}
                hideAddButtonWhenSet
                updateBreakdownFilter={(breakdown_filter) => {
                    let saved: BreakdownFilter | null = breakdown_filter
                    if (breakdown_filter && !breakdown_filter.breakdown_type && !breakdown_filter.breakdowns) {
                        saved = null
                    }
                    m.setBreakdownFilter(saved)
                }}
                updateDisplay={() => {}}
                disablePropertyInfo
                size="small"
            />
        </BindLogic>
    )
}

function PropertiesControl(): JSX.Element {
    const m = useEditModel()
    return (
        <PropertyFilters
            onChange={(properties) => m.setProperties(properties)}
            pageKey={'dashboard_proto_' + m.dashboardId}
            propertyFilters={m.filters.properties}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.EventFeatureFlags,
                TaxonomicFilterGroupType.EventMetadata,
                ...(m.hasPageview ? [TaxonomicFilterGroupType.PageviewUrls] : []),
                ...(m.hasScreen ? [TaxonomicFilterGroupType.Screens] : []),
                TaxonomicFilterGroupType.EmailAddresses,
                ...m.groupsTaxonomicTypes,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.Elements,
                TaxonomicFilterGroupType.SessionProperties,
                TaxonomicFilterGroupType.HogQLExpression,
                TaxonomicFilterGroupType.DataWarehousePersonProperties,
            ]}
        />
    )
}

function GearButton(): JSX.Element {
    return (
        <LemonButton
            icon={<IconGear />}
            size="small"
            tooltip="Configure internal & test user filtering"
            to={urls.settings('project-product-analytics', 'internal-user-filtering')}
        />
    )
}

// Value summaries used by pill/chip variants.
function useOverrideSummaries(): Record<string, { active: boolean; label: string }> {
    const { filters } = useEditModel()
    return {
        date: {
            active: !!filters.date_from || !!filters.date_to,
            label: dateFilterToText(filters.date_from, filters.date_to, 'Date range') ?? 'Date range',
        },
        interval: { active: !!filters.interval, label: filters.interval ? `by ${filters.interval}` : 'Interval' },
        breakdown: { active: !!filters.breakdown_filter, label: 'Breakdown' },
        properties: {
            active: (filters.properties?.length ?? 0) > 0,
            label: `Filters${filters.properties?.length ? ` (${filters.properties.length})` : ''}`,
        },
        testUsers: {
            active: filters.filterTestAccounts !== null && filters.filterTestAccounts !== undefined,
            label: filters.filterTestAccounts === true ? 'Test users excluded' : 'Test users included',
        },
    }
}

// ===== Variant A — compact popover toolbar =====
// Everything collapses to one row of icon pills; each opens its control in a popover.

function Pill({ icon, label, active, control }: PillProps): JSX.Element {
    return (
        <LemonDropdown closeOnClickInside={false} overlay={<div className="p-2 min-w-[16rem]">{control}</div>}>
            <LemonButton size="small" type={active ? 'secondary' : 'tertiary'} icon={icon}>
                <span className={active ? 'font-medium' : 'text-muted'}>{label}</span>
            </LemonButton>
        </LemonDropdown>
    )
}

interface PillProps {
    icon: JSX.Element
    label: string
    active: boolean
    control: JSX.Element
}

function VariantA(): JSX.Element {
    const s = useOverrideSummaries()
    return (
        <div className="flex flex-wrap items-center gap-1">
            <Pill icon={<IconCalendar />} label={s.date.label} active={s.date.active} control={<DateControl />} />
            <Pill
                icon={<IconClock />}
                label={s.interval.label}
                active={s.interval.active}
                control={<IntervalControl />}
            />
            <Pill
                icon={<IconDirectedGraph />}
                label={s.breakdown.label}
                active={s.breakdown.active}
                control={<BreakdownControl />}
            />
            <Pill
                icon={<IconFilter />}
                label={s.properties.label}
                active={s.properties.active}
                control={<PropertiesControl />}
            />
            <Pill
                icon={<IconPerson />}
                label={s.testUsers.active ? s.testUsers.label : 'Test users'}
                active={s.testUsers.active}
                control={
                    <div className="flex items-center gap-1">
                        <TestUsersControl />
                        <GearButton />
                    </div>
                }
            />
            <div className="ml-auto">
                <VariablesForDashboard />
            </div>
        </div>
    )
}

// ===== Variant B — labeled field grid =====
// Every override is a proper labeled field on an aligned grid. No inline prose.

function Field({ label, children }: { label: string; children: JSX.Element }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 min-w-0">
            <LemonLabel className="text-muted text-xs uppercase tracking-wide">{label}</LemonLabel>
            {children}
        </div>
    )
}

function VariantB(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Field label="Date range">
                    <DateControl />
                </Field>
                <Field label="Grouped by">
                    <IntervalControl />
                </Field>
                <Field label="Breakdown">
                    <BreakdownControl />
                </Field>
                <Field label="Internal & test users">
                    <div className="flex items-center gap-1">
                        <TestUsersControl />
                        <GearButton />
                    </div>
                </Field>
            </div>
            <Field label="Property filters">
                <PropertiesControl />
            </Field>
            <VariablesForDashboard />
        </div>
    )
}

// ===== Variant C — chip summary bar =====
// A single line: "+ Add override" plus a removable chip per active override.
// Reveals scale with usage; empty state is a single muted sentence.

interface ChipDef {
    key: string
    label: string
    control: JSX.Element
    reset: () => void
}

function VariantC(): JSX.Element {
    const m = useEditModel()
    const s = useOverrideSummaries()
    // Chips the user explicitly added but that don't yet hold a value.
    const [revealed, setRevealed] = useState<Set<string>>(new Set())

    const reveal = (key: string): void => setRevealed((prev) => new Set(prev).add(key))
    const hide = (key: string): void =>
        setRevealed((prev) => {
            const next = new Set(prev)
            next.delete(key)
            return next
        })

    const defs: ChipDef[] = [
        {
            key: 'date',
            label: s.date.active ? s.date.label : 'Date range',
            control: <DateControl />,
            reset: () => {
                m.setDates(null, null)
                hide('date')
            },
        },
        {
            key: 'interval',
            label: s.interval.active ? s.interval.label : 'Interval',
            control: <IntervalControl />,
            reset: () => {
                m.setInterval(null)
                hide('interval')
            },
        },
        {
            key: 'breakdown',
            label: 'Breakdown',
            control: <BreakdownControl />,
            reset: () => {
                m.setBreakdownFilter(null)
                hide('breakdown')
            },
        },
        {
            key: 'properties',
            label: s.properties.label,
            control: <PropertiesControl />,
            reset: () => {
                m.setProperties([])
                hide('properties')
            },
        },
        {
            key: 'testUsers',
            label: s.testUsers.active ? s.testUsers.label : 'Test users',
            control: (
                <div className="flex items-center gap-1">
                    <TestUsersControl />
                    <GearButton />
                </div>
            ),
            reset: () => {
                m.setFilterTestAccounts(null)
                hide('testUsers')
            },
        },
    ]

    const isActive = (key: string): boolean => (s as any)[key]?.active || revealed.has(key)
    const activeChips = defs.filter((d) => isActive(d.key))
    const inactive = defs.filter((d) => !isActive(d.key))

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonDropdown
                closeOnClickInside
                overlay={
                    <div className="flex flex-col p-1">
                        {inactive.length === 0 ? (
                            <span className="px-2 py-1 text-muted text-xs">All overrides added</span>
                        ) : (
                            inactive.map((d) => (
                                <LemonButton key={d.key} size="small" fullWidth onClick={() => reveal(d.key)}>
                                    {d.label}
                                </LemonButton>
                            ))
                        )}
                    </div>
                }
            >
                <LemonButton size="small" type="secondary" icon={<IconPlus />}>
                    Add override
                </LemonButton>
            </LemonDropdown>

            {activeChips.length === 0 ? (
                <span className="text-muted text-sm">No overrides — insights use their own settings.</span>
            ) : (
                activeChips.map((d) => (
                    <LemonDropdown
                        key={d.key}
                        closeOnClickInside={false}
                        overlay={<div className="p-2 min-w-[16rem]">{d.control}</div>}
                    >
                        <LemonSnack onClose={d.reset}>{d.label}</LemonSnack>
                    </LemonDropdown>
                ))
            )}

            <div className="ml-auto">
                <VariablesForDashboard />
            </div>
        </div>
    )
}

// ===== Variant D — current top bar + labeled panel =====
// Row 1 is untouched (date, grouped-by, advanced toggle, variables). The advanced
// section becomes a shaded panel with a label above every remaining control.

function VariantD(): JSX.Element {
    const { showAdvancedOverrides, advancedOverridesCount } = useValues(dashboardLogic)
    const { toggleAdvancedOverrides } = useActions(dashboardLogic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex gap-2 items-end flex-wrap">
                <DateControl />
                <span className="flex items-center gap-2">
                    <span className="hidden md:inline">grouped by</span>
                    <IntervalControl />
                </span>
                <LemonButton
                    size="small"
                    onClick={toggleAdvancedOverrides}
                    sideIcon={showAdvancedOverrides ? <IconCollapse /> : <IconExpand />}
                >
                    Advanced overrides
                    {advancedOverridesCount > 0 && <span className="ml-1 text-muted">({advancedOverridesCount})</span>}
                </LemonButton>
                <VariablesForDashboard />
            </div>
            {showAdvancedOverrides && (
                <div className="bg-surface-secondary border rounded-lg p-3">
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-start">
                        <Field label="Property filters">
                            <PropertiesControl />
                        </Field>
                        <Field label="Breakdown">
                            <BreakdownControl />
                        </Field>
                        <Field label="Internal & test users">
                            <div className="flex items-center gap-1">
                                <TestUsersControl />
                                <GearButton />
                            </div>
                        </Field>
                    </div>
                </div>
            )}
        </div>
    )
}

// Variant E uses the insights test-account filter (a switch) instead of the tri-state dropdown.
// The switch is binary, so the "each insight's setting" (null) override isn't reachable here.
// TestAccountFilter hardcodes fullWidth (0.75rem label); override both so it sits inline next to
// the breakdown at the same 0.875rem font size.
function InsightsTestAccountControl(): JSX.Element {
    const m = useEditModel()
    return (
        <div className="[&_.LemonSwitch--full-width]:w-auto [&_.LemonSwitch_label]:text-sm">
            <TestAccountFilter
                size="small"
                filters={{ filter_test_accounts: m.filters.filterTestAccounts ?? false }}
                onChange={({ filter_test_accounts }) => m.setFilterTestAccounts(!!filter_test_accounts)}
            />
        </div>
    )
}

// ===== Variants E & F — filters inline + variables below =====
// Top bar keeps date + grouped-by and adds the always-visible Filters button next to
// the interval. The advanced panel holds breakdown + test users. Variables sit below,
// always visible. F is E with the advanced panel's shaded background removed.

function InlineFiltersLayout({ shaded }: { shaded: boolean }): JSX.Element {
    const { showAdvancedOverrides, advancedOverridesCount } = useValues(dashboardLogic)
    const { toggleAdvancedOverrides } = useActions(dashboardLogic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex gap-2 items-end flex-wrap">
                <DateControl />
                <span className="flex items-center gap-2">
                    <span className="hidden md:inline">grouped by</span>
                    <IntervalControl />
                </span>
                <PropertiesControl />
                <LemonButton
                    size="small"
                    onClick={toggleAdvancedOverrides}
                    sideIcon={showAdvancedOverrides ? <IconCollapse /> : <IconExpand />}
                >
                    Advanced overrides
                    {advancedOverridesCount > 0 && <span className="ml-1 text-muted">({advancedOverridesCount})</span>}
                </LemonButton>
            </div>
            {showAdvancedOverrides && (
                <div className={shaded ? 'bg-surface-secondary border rounded-lg p-3' : undefined}>
                    <div className="flex flex-wrap items-center gap-2">
                        <BreakdownControl />
                        <InsightsTestAccountControl />
                    </div>
                </div>
            )}
            {/* Shrink the list-variable clear (×) from the default 1.25rem small-button icon down to the value-text size. */}
            <div className="[&_.LemonButtonWithSideAction\_\_side-button_.LemonButton]:[--lemon-button-icon-size:0.875rem]">
                <VariablesForDashboard />
            </div>
        </div>
    )
}

function VariantE(): JSX.Element {
    return <InlineFiltersLayout shaded />
}

function VariantF(): JSX.Element {
    return <InlineFiltersLayout shaded={false} />
}

// ===== Switcher (dev only) =====

function currentVariant(searchParams?: Record<string, any>): PrototypeVariant | null {
    const v = (searchParams ?? router.values.searchParams).variant
    return PROTOTYPE_VARIANTS.includes(v) ? (v as PrototypeVariant) : null
}

function goToVariant(v: PrototypeVariant | null): void {
    const { pathname } = router.values.location
    const params = { ...router.values.searchParams }
    if (v) {
        params.variant = v
    } else {
        delete params.variant
    }
    router.actions.push(pathname, params, router.values.hashParams)
}

export function PrototypeSwitcher(): JSX.Element | null {
    const { searchParams } = useValues(router)
    const active = PROTOTYPE_VARIANTS.includes(searchParams.variant) ? (searchParams.variant as PrototypeVariant) : null

    useEffect(() => {
        const onKey = (e: KeyboardEvent): void => {
            const el = document.activeElement
            if (el && ['INPUT', 'TEXTAREA'].includes(el.tagName)) {
                return
            }
            if ((el as HTMLElement)?.isContentEditable) {
                return
            }
            if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') {
                return
            }
            const order: (PrototypeVariant | null)[] = [null, ...PROTOTYPE_VARIANTS]
            const idx = order.indexOf(active)
            const nextIdx = e.key === 'ArrowRight' ? (idx + 1) % order.length : (idx - 1 + order.length) % order.length
            goToVariant(order[nextIdx])
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    }, [active])

    if (process.env.NODE_ENV === 'production') {
        return null
    }

    const order: (PrototypeVariant | null)[] = [null, ...PROTOTYPE_VARIANTS]
    const idx = order.indexOf(active)
    const prev = order[(idx - 1 + order.length) % order.length]
    const next = order[(idx + 1) % order.length]

    return (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[10000] flex w-80 items-center justify-between gap-2 rounded-full bg-black text-white shadow-lg px-3 py-1.5">
            <button
                type="button"
                className="flex items-center justify-center text-white text-lg hover:opacity-70"
                onClick={() => goToVariant(prev)}
            >
                <IconChevronLeft />
            </button>
            <span className="text-xs font-mono whitespace-nowrap overflow-hidden text-ellipsis text-center flex-1">
                edit-bar: {active ? `${active} — ${VARIANT_NAMES[active]}` : 'original'}
            </span>
            <button
                type="button"
                className="flex items-center justify-center text-white text-lg hover:opacity-70"
                onClick={() => goToVariant(next)}
            >
                <IconChevronRight />
            </button>
        </div>
    )
}

export function DashboardEditBarPrototype({ variant }: { variant: PrototypeVariant }): JSX.Element {
    switch (variant) {
        case 'A':
            return <VariantA />
        case 'B':
            return <VariantB />
        case 'C':
            return <VariantC />
        case 'D':
            return <VariantD />
        case 'E':
            return <VariantE />
        case 'F':
            return <VariantF />
    }
}

export { currentVariant }
