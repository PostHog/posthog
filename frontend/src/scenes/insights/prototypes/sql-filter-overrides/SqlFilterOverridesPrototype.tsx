import { useValues } from 'kea'
import { router } from 'kea-router'
/**
 * PROTOTYPE — throwaway, do not merge. See PROTOTYPE.md in this folder.
 *
 * Question: SQL insights using {filters} can only be filtered by editing the insight.
 * What should view-time filter overrides look like?
 *
 * Three variants on the existing insight view route, gated by `?variant=A|B|C` (dev only):
 *   A — Classic insight card: bordered card like a trends insight, date range in the top row
 *       inside the border, results attached below, immediate apply
 *   B — Overrides panel: staged panel comparing saved filters vs overrides, explicit apply
 *   C — Editable summary: prose line whose segments edit in place
 *
 * All variants write the existing `?filters_override=` URL param (the mechanism dashboards
 * already use), so results really re-run and nothing is persisted.
 */
import { useEffect, useState } from 'react'

import { IconCalendar, IconFilter } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dateFilterToText, dateMapping } from 'lib/utils/dateFilters'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'

import { DashboardFilter, HogQLFilters, Node } from '~/queries/schema/schema-general'
import { containsHogQLQuery, isDataTableNode, isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'
import { AnyPropertyFilter, ItemMode } from '~/types'

const VARIANT_KEYS = ['A', 'B', 'C'] as const
type VariantKey = (typeof VARIANT_KEYS)[number]
const VARIANT_NAMES: Record<VariantKey, string> = {
    A: 'Classic insight card',
    B: 'Overrides panel',
    C: 'Editable summary',
}

const TAXONOMIC_GROUPS = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.SessionProperties,
    TaxonomicFilterGroupType.HogQLExpression,
]

function isOverrideEmpty(overrides: DashboardFilter | null): boolean {
    return !overrides || (!overrides.date_from && !overrides.date_to && !overrides.properties?.length)
}

function savedHogQLFilters(query: Node | null): HogQLFilters {
    if (!query) {
        return {}
    }
    const source = isDataVisualizationNode(query) || isDataTableNode(query) ? query.source : query
    return isHogQLQuery(source) ? (source.filters ?? {}) : {}
}

function propertyLabel(property: AnyPropertyFilter, index: number): string {
    if ('key' in property && property.key != null) {
        return String(property.key)
    }
    return `filter ${index + 1}`
}

function setOverrides(next: DashboardFilter | null): void {
    const params = { ...router.values.searchParams }
    if (next && !isOverrideEmpty(next)) {
        params['filters_override'] = next
    } else {
        delete params['filters_override']
    }
    router.actions.replace(router.values.location.pathname, params, router.values.hashParams)
}

function cycleVariant(delta: number): void {
    const current = String(router.values.searchParams['variant'] ?? 'A').toUpperCase() as VariantKey
    const index = Math.max(VARIANT_KEYS.indexOf(current), 0)
    const next = VARIANT_KEYS[(index + delta + VARIANT_KEYS.length) % VARIANT_KEYS.length]
    router.actions.replace(
        router.values.location.pathname,
        { ...router.values.searchParams, variant: next },
        router.values.hashParams
    )
}

function exitPrototype(): void {
    const params = { ...router.values.searchParams }
    delete params['variant']
    router.actions.replace(router.values.location.pathname, params, router.values.hashParams)
}

interface VariantProps {
    overrides: DashboardFilter
    saved: HogQLFilters
}

/**
 * Variant A — looks like a classic insight. Reuses the exact InsightVizDisplay /
 * InsightDisplayConfig classes and the InsightDateFilter configuration, so the card is
 * pixel-identical to a trends insight — except changes write filter overrides, not the insight.
 * The date filter shows the effective range: the override if set, else the saved one.
 */
function VariantClassicCard({ overrides, saved, children }: VariantProps & { children: React.ReactNode }): JSX.Element {
    return (
        <div className="InsightVizDisplay InsightVizDisplay--type-trends border rounded bg-surface-primary">
            <div className="InsightDisplayConfig @container flex justify-between items-center flex-wrap gap-2 [&_.LemonButton--small]:[--lemon-button-gap:0.25rem] [&_.LemonButton--small]:[--lemon-button-padding-horizontal:0.375rem]">
                <div className="flex items-center gap-x-2 flex-wrap gap-y-2">
                    <span className="flex items-center gap-x-2 text-sm">
                        <DateFilter
                            showExplicitDateToggle
                            allowTimePrecision
                            allowFixedRangeWithTime
                            dateFrom={overrides.date_from ?? saved.dateRange?.date_from ?? null}
                            dateTo={overrides.date_to ?? saved.dateRange?.date_to ?? null}
                            explicitDate={overrides.explicitDate ?? saved.dateRange?.explicitDate ?? false}
                            onChange={(date_from, date_to, explicitDate) =>
                                setOverrides({ ...overrides, date_from, date_to, explicitDate })
                            }
                            dateOptions={dateMapping}
                            allowedRollingDateOptions={['hours', 'days', 'weeks', 'months', 'years']}
                            makeLabel={(key) => (
                                <>
                                    <IconCalendar /> {key}
                                </>
                            )}
                        />
                    </span>
                    <span className="flex items-center gap-x-2 text-sm">
                        <PropertyFilters
                            pageKey="sql-overrides-prototype-a"
                            buttonSize="small"
                            propertyFilters={overrides.properties ?? []}
                            onChange={(properties) => setOverrides({ ...overrides, properties })}
                            taxonomicGroupTypes={TAXONOMIC_GROUPS}
                            addText="Add filter"
                        />
                    </span>
                </div>
                <div className="flex items-center gap-x-2">
                    {!isOverrideEmpty(overrides) && (
                        <LemonButton size="small" onClick={() => setOverrides(null)}>
                            Reset to saved
                        </LemonButton>
                    )}
                </div>
            </div>
            <div className="InsightVizDisplay__content">{children}</div>
        </div>
    )
}

/** Variant B — one button opens a staged panel: saved filters next to overrides, explicit apply. */
function VariantOverridesPanel({ overrides, saved }: VariantProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const [draft, setDraft] = useState<DashboardFilter>(overrides)
    const overrideCount = (overrides.properties?.length ?? 0) + (overrides.date_from || overrides.date_to ? 1 : 0)
    const savedDateLabel = dateFilterToText(saved.dateRange?.date_from, saved.dateRange?.date_to, 'all time')

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-end">
                <LemonButton
                    size="small"
                    type={overrideCount ? 'primary' : 'secondary'}
                    icon={<IconFilter />}
                    onClick={() => {
                        setDraft(overrides)
                        setOpen(!open)
                    }}
                >
                    Filter overrides{overrideCount ? ` (${overrideCount})` : ''}
                </LemonButton>
            </div>
            {open && (
                <div className="grid grid-cols-1 gap-4 rounded-lg border bg-surface-primary p-4 md:grid-cols-2">
                    <div className="flex flex-col gap-2">
                        <h5 className="mb-0">Saved on this insight</h5>
                        <div className="flex items-center gap-2 text-sm">
                            <span className="text-secondary">Date range:</span> {savedDateLabel}
                        </div>
                        <div className="flex flex-wrap items-center gap-1 text-sm">
                            <span className="text-secondary">Properties:</span>
                            {saved.properties?.length ? (
                                saved.properties.map((property, index) => (
                                    <LemonTag key={index}>{propertyLabel(property, index)}</LemonTag>
                                ))
                            ) : (
                                <span>none</span>
                            )}
                        </div>
                        <p className="m-0 text-xs text-secondary">
                            Changing these means editing the insight. Overrides on the right only change what you see.
                        </p>
                    </div>
                    <div className="flex flex-col gap-2 md:border-l md:pl-4">
                        <h5 className="mb-0">Your overrides</h5>
                        <div className="flex items-center gap-2">
                            <DateFilter
                                size="small"
                                dateFrom={draft.date_from ?? null}
                                dateTo={draft.date_to ?? null}
                                placeholder="Keep saved date range"
                                onChange={(date_from, date_to) => setDraft({ ...draft, date_from, date_to })}
                            />
                            {(draft.date_from || draft.date_to) && (
                                <span className="text-xs text-warning">replaces the saved date range</span>
                            )}
                        </div>
                        <PropertyFilters
                            pageKey="sql-overrides-prototype-b"
                            buttonSize="small"
                            propertyFilters={draft.properties ?? []}
                            onChange={(properties) => setDraft({ ...draft, properties })}
                            taxonomicGroupTypes={TAXONOMIC_GROUPS}
                            addText="Add filter (applies on top of saved)"
                        />
                        <div className="flex justify-end gap-2">
                            <LemonButton size="small" type="tertiary" onClick={() => setOpen(false)}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                size="small"
                                type="tertiary"
                                status="danger"
                                disabledReason={
                                    isOverrideEmpty(overrides) && isOverrideEmpty(draft)
                                        ? 'Nothing to clear'
                                        : undefined
                                }
                                onClick={() => {
                                    setDraft({})
                                    setOverrides(null)
                                    setOpen(false)
                                }}
                            >
                                Clear
                            </LemonButton>
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={() => {
                                    setOverrides(draft)
                                    setOpen(false)
                                }}
                            >
                                Apply
                            </LemonButton>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

/** Variant C — a prose summary line; each segment edits in place, immediate apply. */
function VariantEditableSummary({ overrides, saved }: VariantProps): JSX.Element {
    const dateOverridden = Boolean(overrides.date_from || overrides.date_to)
    const savedDateLabel = dateFilterToText(saved.dateRange?.date_from, saved.dateRange?.date_to, 'all time')
    const overridden = !isOverrideEmpty(overrides)

    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm">
                <span className="text-secondary">Showing</span>
                <DateFilter
                    size="xsmall"
                    type={dateOverridden ? 'secondary' : 'tertiary'}
                    dateFrom={overrides.date_from ?? null}
                    dateTo={overrides.date_to ?? null}
                    placeholder={savedDateLabel ?? 'all time'}
                    onChange={(date_from, date_to) => setOverrides({ ...overrides, date_from, date_to })}
                />
                <span className="text-secondary">where</span>
                <PropertyFilters
                    pageKey="sql-overrides-prototype-c"
                    buttonSize="xsmall"
                    propertyFilters={overrides.properties ?? []}
                    onChange={(properties) => setOverrides({ ...overrides, properties })}
                    taxonomicGroupTypes={TAXONOMIC_GROUPS}
                    addText={overrides.properties?.length ? '+' : 'anything — add a filter'}
                />
                {overridden && (
                    <>
                        <LemonTag type="warning">overridden</LemonTag>
                        <LemonButton size="xsmall" type="tertiary" onClick={() => setOverrides(null)}>
                            Reset to saved
                        </LemonButton>
                    </>
                )}
            </div>
            <div className="text-xs text-secondary">
                {overridden ? (
                    <>
                        Saved: {savedDateLabel}
                        {saved.properties?.length ? ` · ${saved.properties.length} saved filters still apply` : ''} —
                        the insight itself is unchanged.
                    </>
                ) : (
                    <>Adjust the view without editing the insight — nothing gets saved.</>
                )}
            </div>
        </div>
    )
}

/** Floating bottom bar: cycle variants (arrows or ←/→ keys), see current override state, exit. */
function PrototypeSwitcher({ variant, overrides }: { variant: VariantKey; overrides: DashboardFilter }): JSX.Element {
    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            const target = event.target as HTMLElement | null
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
                return
            }
            if (event.key === 'ArrowLeft') {
                cycleVariant(-1)
            } else if (event.key === 'ArrowRight') {
                cycleVariant(1)
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [])

    const overridesJson = isOverrideEmpty(overrides) ? 'no overrides' : JSON.stringify(overrides)

    return (
        <div className="fixed bottom-4 left-1/2 z-[1200] flex -translate-x-1/2 items-center gap-3 rounded-full bg-black/85 px-4 py-2 text-white shadow-xl">
            <button
                type="button"
                className="cursor-pointer text-lg leading-none"
                onClick={() => cycleVariant(-1)}
                aria-label="Previous variant"
            >
                ‹
            </button>
            <div className="flex min-w-40 flex-col items-center">
                <span className="text-xs font-semibold">
                    {variant} — {VARIANT_NAMES[variant]}
                </span>
                <code className="max-w-80 truncate text-[10px] opacity-60" title={overridesJson}>
                    {overridesJson}
                </code>
            </div>
            <button
                type="button"
                className="cursor-pointer text-lg leading-none"
                onClick={() => cycleVariant(1)}
                aria-label="Next variant"
            >
                ›
            </button>
            <button
                type="button"
                className="ml-1 cursor-pointer text-xs opacity-60 hover:opacity-100"
                onClick={exitPrototype}
                aria-label="Exit prototype"
            >
                ✕
            </button>
        </div>
    )
}

export function SqlFilterOverridesPrototype({
    query,
    children,
}: {
    query: Node | null
    children: React.ReactNode
}): JSX.Element {
    const { insightId, insightMode, filtersOverride } = useValues(insightSceneLogic)
    const { searchParams } = useValues(router)

    const variantParam = searchParams['variant']
    const variant =
        typeof variantParam === 'string' && VARIANT_KEYS.includes(variantParam.toUpperCase() as VariantKey)
            ? (variantParam.toUpperCase() as VariantKey)
            : null
    if (
        process.env.NODE_ENV === 'production' ||
        !variant ||
        insightMode !== ItemMode.View ||
        !insightId ||
        insightId === 'new' ||
        !containsHogQLQuery(query)
    ) {
        return <>{children}</>
    }

    const overrides: DashboardFilter = filtersOverride ?? {}
    const saved = savedHogQLFilters(query)

    return (
        <>
            {variant === 'A' ? (
                <VariantClassicCard overrides={overrides} saved={saved}>
                    {children}
                </VariantClassicCard>
            ) : (
                <>
                    {variant === 'B' && <VariantOverridesPanel overrides={overrides} saved={saved} />}
                    {variant === 'C' && <VariantEditableSummary overrides={overrides} saved={saved} />}
                    {children}
                </>
            )}
            <PrototypeSwitcher variant={variant} overrides={overrides} />
        </>
    )
}
