import { LemonSelect, LemonSelectOptionLeaf } from '@posthog/lemon-ui'

import { DataModelingSyncInterval } from '~/types'

import { SyncFrequencyBoundsApi } from 'products/data_warehouse/frontend/generated/api.schemas'

export type SyncFrequencyValue = DataModelingSyncInterval | 'never'

/**
 * Target wording, not interval wording: a cadence is a promise about how stale data may get, and the
 * two bounds read as one range only when both ends describe the same thing.
 */
const CADENCE_LABELS: Record<DataModelingSyncInterval, string> = {
    '15min': 'No older than 15 minutes',
    '30min': 'No older than 30 minutes',
    '1hour': 'No older than 1 hour',
    '6hour': 'No older than 6 hours',
    '12hour': 'No older than 12 hours',
    '24hour': 'No older than 1 day',
    '7day': 'No older than 1 week',
    '30day': 'No older than 30 days',
}

const ORDERED_CADENCES = Object.keys(CADENCE_LABELS) as DataModelingSyncInterval[]

const NEVER_OPTION: LemonSelectOptionLeaf<SyncFrequencyValue> = {
    value: 'never',
    label: "Don't refresh",
}

/**
 * Why the picker is read-only, for the modes where cadence is not this view's to set.
 *
 * `no_node` is deliberately absent. A view missing from the modeling graph has no bounds to show, but
 * disabling there would leave the one population that most needs a way forward with a locked control.
 */
const MODE_DISABLED_REASONS: Record<string, string> = {
    dag_schedule: "This project runs one schedule per DAG, so this view follows its DAG's frequency.",
    managed_viewset: 'PostHog manages this view, including how often it refreshes.',
}

export interface SyncFrequencySelectProps {
    /** Bounds from the saved query. Undefined while loading, or on surfaces that don't fetch them. */
    bounds?: SyncFrequencyBoundsApi | null
    value: SyncFrequencyValue | null
    onChange: (value: SyncFrequencyValue) => void
    /** Offer "Don't refresh". Only meaningful once a view is materialized, since it stops a live schedule. */
    includeNever?: boolean
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
    includeNever,
    loading,
    disabledReason,
    'data-attr': dataAttr,
}: SyncFrequencySelectProps): JSX.Element {
    const options = buildOptions(bounds)
    const explanation = buildExplanation(bounds)
    const reason =
        disabledReason ??
        unsatisfiableReason(bounds) ??
        (bounds ? MODE_DISABLED_REASONS[bounds.frequency_mode] : undefined)

    return (
        <div className="flex flex-col gap-1">
            <LemonSelect<SyncFrequencyValue>
                size="small"
                value={value ?? undefined}
                onChange={(next) => next && onChange(next)}
                options={includeNever ? [NEVER_OPTION, ...options] : options}
                loading={loading}
                disabledReason={reason}
                data-attr={dataAttr}
            />
            {explanation && <span className="text-xs text-secondary">{explanation}</span>}
        </div>
    )
}

export function buildOptions(bounds?: SyncFrequencyBoundsApi | null): LemonSelectOptionLeaf<SyncFrequencyValue>[] {
    if (!bounds?.options.length) {
        return ORDERED_CADENCES.map((cadence) => ({ value: cadence, label: CADENCE_LABELS[cadence] }))
    }

    return bounds.options.map((option) => {
        const cadence = option.cadence as DataModelingSyncInterval
        return {
            value: cadence,
            label: CADENCE_LABELS[cadence],
            disabledReason: option.allowed ? undefined : blockedReason(option, bounds),
        }
    })
}

function blockedReason(option: SyncFrequencyBoundsApi['options'][number], bounds: SyncFrequencyBoundsApi): string {
    const name = option.blocker?.name
    if (option.blocked_by === 'source' && name && bounds.floor) {
        return `${name} delivers every ${bounds.floor.label}, so this view can't be fresher than that.`
    }
    if (option.blocked_by === 'consumer' && name && bounds.ceiling) {
        return `${name} needs data no older than ${bounds.ceiling.label}, so this view can't be slower than that.`
    }
    return 'Not available for this view.'
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

    const source = bounds.floor?.blocker?.name ?? 'the sources this query reads'
    const consumer = bounds.ceiling?.blocker?.name ?? 'a view or endpoint built on this one'
    if (bounds.floor && bounds.ceiling) {
        return (
            `No cadence works here: ${source} only delivers new data every ${bounds.floor.label}, ` +
            `but ${consumer} needs data no older than ${bounds.ceiling.label}. ` +
            `Slow down ${consumer} or speed up ${source}.`
        )
    }
    if (bounds.floor) {
        return (
            `No cadence works here: ${source} only delivers new data every ${bounds.floor.label}, ` +
            `slower than any cadence this can be set to. Speed up ${source} first.`
        )
    }
    if (bounds.ceiling) {
        return `No cadence works here: ${consumer} needs data no older than ${bounds.ceiling.label}.`
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
    const floorName = bounds.floor?.blocker?.name ?? 'An upstream source'
    const ceilingName = bounds.ceiling?.blocker?.name ?? 'A downstream view'

    if (bounds.floor && bounds.ceiling) {
        parts.push(
            `Set this between ${bounds.floor.label} and ${bounds.ceiling.label}. ` +
                `${floorName} delivers every ${bounds.floor.label}, ` +
                `and ${ceilingName} needs data no older than ${bounds.ceiling.label}.`
        )
    } else if (bounds.floor) {
        parts.push(`${floorName} delivers every ${bounds.floor.label}, so this can't be fresher than that.`)
    } else if (bounds.ceiling) {
        parts.push(
            `${ceilingName} needs data no older than ${bounds.ceiling.label}, so this can't be slower than that.`
        )
    }

    if (bounds.best_effort_sources.length) {
        const names = bounds.best_effort_sources.map((source) => source.name).join(', ')
        const verb = bounds.best_effort_sources.length > 1 ? 'have' : 'has'
        parts.push(`${names} ${verb} no sync schedule, so this view may still serve data older than you pick.`)
    }

    return parts.length ? parts.join(' ') : null
}
