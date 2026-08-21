import { IconRabbit, IconTortoise } from '@posthog/icons'
import { LemonLabel, LemonSegmentedButton, LemonSegmentedButtonOption } from '@posthog/lemon-ui'

import { DataModelingSyncInterval } from '~/types'

import { SyncFrequencyBoundsApi } from 'products/data_warehouse/frontend/generated/api.schemas'

export type SyncFrequencyValue = DataModelingSyncInterval | 'never'

/**
 * Interval wording ("refresh every X"), which the bounds are what make truthful: a view may only be
 * set at or below its consumers' cadence, so the value picked here is the cadence that runs, not a
 * request the scheduler quietly tightens. The bar carries the wording once in its label, so each
 * segment only has to say which duration it is.
 */
const CADENCE_LABELS: Record<DataModelingSyncInterval, string> = {
    '15min': '15 minutes',
    '30min': '30 minutes',
    '1hour': '1 hour',
    '6hour': '6 hours',
    '12hour': '12 hours',
    '24hour': '1 day',
    '7day': '7 days',
    '30day': '30 days',
}

const CADENCE_SEGMENTS: Record<DataModelingSyncInterval, string> = {
    '15min': '15m',
    '30min': '30m',
    '1hour': '1h',
    '6hour': '6h',
    '12hour': '12h',
    '24hour': '1d',
    '7day': '7d',
    '30day': '30d',
}

const ORDERED_CADENCES = Object.keys(CADENCE_LABELS) as DataModelingSyncInterval[]

/**
 * Decorative, so `aria-hidden`: they only restate which way the bar runs, which the segment labels
 * already say outright.
 */
const PACE_ICON_CLASS = 'text-xl text-secondary shrink-0'

/**
 * Why the cadence controls are read-only, for the modes where cadence is not this view's to set.
 *
 * `no_node` belongs here despite having no bounds to show: the missing-node guard refuses every
 * cadence write, so a live control only buys a 400. The reason carries the way out instead.
 */
const MODE_DISABLED_REASONS: Record<string, string> = {
    dag_schedule: "This project runs one schedule per DAG, so this view follows its DAG's frequency.",
    managed_viewset: 'PostHog manages this view, including how often it refreshes.',
    no_node: 'This view is not set up for scheduled refreshes yet. Save it again, then pick a cadence.',
}

/** Why the view's frequency mode locks its cadence controls, or null where the mode allows them. */
export function modeDisabledReason(bounds?: SyncFrequencyBoundsApi | null): string | null {
    return (bounds && MODE_DISABLED_REASONS[bounds.frequency_mode]) || null
}

export interface SyncFrequencySelectProps {
    /** Bounds from the saved query. Undefined while loading, or on surfaces that don't fetch them. */
    bounds?: SyncFrequencyBoundsApi | null
    /** A paused view ("never") leaves the bar with nothing selected, since pausing is not a cadence. */
    value: SyncFrequencyValue | null
    onChange: (value: DataModelingSyncInterval) => void
    /** Locks the bar while a change is in flight, so one click can't queue eight cadence writes. */
    loading?: boolean
    /** Takes precedence over the mode's own reason, so access checks win over scheduling ones. */
    disabledReason?: string
    'data-attr'?: string
}

/**
 * A cadence picker that offers only what the scheduler will honor, and names what withholds the rest.
 *
 * Without bounds it degrades to every cadence, which is what teams whose backend accepts any of them
 * should see.
 */
export function SyncFrequencySelect({
    bounds,
    value,
    onChange,
    loading,
    disabledReason,
    'data-attr': dataAttr,
}: SyncFrequencySelectProps): JSX.Element {
    const options = buildOptions(bounds)
    const explanation = buildExplanation(bounds)
    const reason =
        disabledReason ??
        (loading ? 'Saving the new cadence.' : undefined) ??
        unsatisfiableReason(bounds) ??
        modeDisabledReason(bounds) ??
        undefined

    return (
        <div className="flex flex-col gap-1 items-start" data-attr={dataAttr}>
            <LemonLabel>Refresh every</LemonLabel>
            <div className="flex items-center gap-2">
                <IconRabbit className={PACE_ICON_CLASS} aria-hidden />
                <LemonSegmentedButton<DataModelingSyncInterval>
                    size="small"
                    value={value && value !== 'never' ? value : undefined}
                    onChange={(next) => onChange(next)}
                    options={options}
                    disabledReason={reason}
                />
                <IconTortoise className={PACE_ICON_CLASS} aria-hidden />
            </div>
            {explanation && <span className="text-xs text-secondary max-w-prose">{explanation}</span>}
        </div>
    )
}

export function buildOptions(
    bounds?: SyncFrequencyBoundsApi | null
): LemonSegmentedButtonOption<DataModelingSyncInterval>[] {
    if (!bounds?.options.length) {
        return ORDERED_CADENCES.map((cadence) => segment(cadence))
    }

    return bounds.options.map((option) => {
        const cadence = option.cadence as DataModelingSyncInterval
        return {
            ...segment(cadence),
            disabledReason: option.allowed ? undefined : blockedReason(option, bounds),
        }
    })
}

/** Abbreviated on the bar, spelled out on hover, so eight segments stay readable at one glance. */
function segment(cadence: DataModelingSyncInterval): LemonSegmentedButtonOption<DataModelingSyncInterval> {
    return { value: cadence, label: CADENCE_SEGMENTS[cadence], tooltip: `Every ${CADENCE_LABELS[cadence]}` }
}

/**
 * Terse on purpose: the line under the bar already spells out both bounds, so a segment only has to
 * say which direction it falls outside and who holds that end.
 *
 * A blocker the caller may not read arrives as `null`, so keep the direction and drop the name
 * rather than falling through to something that says neither.
 */
function blockedReason(option: SyncFrequencyBoundsApi['options'][number], bounds: SyncFrequencyBoundsApi): string {
    const name = option.blocker?.name
    if (option.blocked_by === 'source' && bounds.floor) {
        return name ? `More often than ${name} syncs` : 'More often than the sources this view reads'
    }
    if (option.blocked_by === 'consumer' && bounds.ceiling) {
        return name ? `Too slow for ${name}` : 'Too slow for something built on this view'
    }
    return 'Not available for this view'
}

/**
 * Why no cadence at all can be picked, when a view's lineage leaves an empty range.
 *
 * Not the same as having no bounds: an empty `options` list means unbounded, while options that are
 * all blocked mean a floor above the ceiling, which the backend refuses whatever gets submitted.
 * Callers offering a Materialize action must gate it on this, since there is nothing to fall back to.
 */
export function unsatisfiableReason(bounds?: SyncFrequencyBoundsApi | null): string | null {
    if (!bounds?.options.length || bounds.options.some((option) => option.allowed)) {
        return null
    }

    const source = bounds.floor?.blocker?.name ?? 'an upstream source'
    const consumer = bounds.ceiling?.blocker?.name ?? 'a view or endpoint built on this one'
    if (bounds.floor && bounds.ceiling) {
        return (
            `No cadence works here: ${source} only syncs every ${bounds.floor.label}, ` +
            `but ${consumer} refreshes every ${bounds.ceiling.label}. ` +
            `Slow down ${consumer} or speed up ${source}.`
        )
    }
    if (bounds.floor) {
        return (
            `No cadence works here: ${source} only syncs every ${bounds.floor.label}, ` +
            `less often than anything this can refresh at. Speed up ${source} first.`
        )
    }
    if (bounds.ceiling) {
        return (
            `No cadence works here: ${consumer} refreshes every ${bounds.ceiling.label}, ` +
            `more often than anything this can refresh at. Slow down ${consumer} first.`
        )
    }
    return 'No cadence works here.'
}

/**
 * A cadence to start a never-materialized view on, given what its lineage allows.
 *
 * `preferred` is a fixed default, so on a view with a sub-daily consumer it names a cadence the
 * backend refuses — the picker would open on a greyed-out row and Materialize would 400. Falls back
 * to the coarsest allowed cadence no coarser than `preferred`, so a first run stays as cheap as the
 * lineage permits. When nothing is allowed there is no such fallback, so it returns `preferred`
 * unchanged and `unsatisfiableReason` is what keeps the action out of reach.
 */
export function defaultCadenceWithin(
    bounds: SyncFrequencyBoundsApi | null | undefined,
    preferred: DataModelingSyncInterval
): DataModelingSyncInterval {
    const allowed = (bounds?.options ?? [])
        .filter((option) => option.allowed)
        .map((option) => option.cadence as DataModelingSyncInterval)
    if (!allowed.length || allowed.includes(preferred)) {
        return preferred
    }

    const rank = (cadence: DataModelingSyncInterval): number => ORDERED_CADENCES.indexOf(cadence)
    const upToPreferred = allowed.filter((cadence) => rank(cadence) <= rank(preferred))
    const pool = upToPreferred.length ? upToPreferred : allowed
    return pool.reduce((coarsest, cadence) => (rank(cadence) > rank(coarsest) ? cadence : coarsest))
}

export function buildExplanation(bounds?: SyncFrequencyBoundsApi | null): string | null {
    if (!bounds || bounds.frequency_mode !== 'tiered') {
        return null
    }

    const parts: string[] = []
    // A withheld blocker still has to hold its slot in the sentence, and the two slots read
    // differently: one opens a sentence, one sits mid-clause.
    const floorName = bounds.floor?.blocker?.name ?? 'An upstream source'
    const ceilingLead = bounds.ceiling?.blocker?.name ?? 'A downstream view'
    const ceilingMid = bounds.ceiling?.blocker?.name ?? 'a downstream view'

    if (bounds.floor && bounds.ceiling) {
        parts.push(
            `Pick between ${bounds.floor.label} and ${bounds.ceiling.label}. ` +
                `${floorName} syncs every ${bounds.floor.label}, ` +
                `and ${ceilingMid} refreshes every ${bounds.ceiling.label}.`
        )
    } else if (bounds.floor) {
        parts.push(`${floorName} syncs every ${bounds.floor.label}, so this can't refresh more often.`)
    } else if (bounds.ceiling) {
        parts.push(`${ceilingLead} refreshes every ${bounds.ceiling.label}, so this can't refresh less often.`)
    }

    const named = bounds.best_effort_sources.map((source) => source.name).filter(Boolean)
    if (named.length || bounds.best_effort_sources_withheld) {
        const subject = named.length
            ? `${named.join(', ')}${bounds.best_effort_sources_withheld ? ' and other sources upstream' : ''}`
            : 'Some sources upstream'
        const plural = named.length > 1 || bounds.best_effort_sources_withheld || !named.length
        parts.push(
            `${subject} ${plural ? 'have' : 'has'} no sync schedule, ` +
                `so refreshing more often won't make that data any newer.`
        )
    }

    return parts.length ? parts.join(' ') : null
}
