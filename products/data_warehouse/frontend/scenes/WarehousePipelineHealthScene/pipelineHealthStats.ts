import { dayjs } from 'lib/dayjs'

import type {
    ManagedWarehouseDataStatusResponseApi,
    ManagedWarehouseLandingHistoryResponseApi,
    ManagedWarehouseLandingStateEnumApi,
    ManagedWarehouseSourceSummaryApi,
} from '../../generated/api.schemas'
import { formatCount, formatDuration } from '../WarehouseConsole/warehouseConsoleFormat'
import type { RunBucket } from '../WarehouseConsole/WarehouseRunBars'

export type HistoryDays = 7 | 30

export const LANDING_STATES: ManagedWarehouseLandingStateEnumApi[] = [
    'in_sync',
    'behind',
    'failing',
    'not_in_warehouse',
    'paused',
]

/** How many datasets (events, persons) and imported tables are in one landing state. */
export interface LandingCount {
    datasets: number
    tables: number
}

export type LandingTotals = Record<ManagedWarehouseLandingStateEnumApi, LandingCount>

/** Counts every item the warehouse holds: one per dataset by its landing state, plus every schema of every source. */
export function landingTotals(status: ManagedWarehouseDataStatusResponseApi): LandingTotals {
    const totals = Object.fromEntries(
        LANDING_STATES.map((state) => [state, { datasets: 0, tables: 0 }])
    ) as LandingTotals
    for (const dataset of [status.events, status.persons]) {
        totals[dataset.landing_state].datasets += 1
    }
    for (const source of status.sources.sources) {
        for (const state of LANDING_STATES) {
            totals[state].tables += source.landing_counts[state]
        }
    }
    return totals
}

export interface LandingTile {
    state: ManagedWarehouseLandingStateEnumApi
    label: string
    value: string
    detail: string
    note?: string
}

const plural = (count: number, noun: string): string => `${formatCount(count)} ${noun}${count === 1 ? '' : 's'}`

/** The split of a count between datasets and tables, leaving out the kind that has none. */
function splitDetail({ datasets, tables }: LandingCount): string {
    const parts = [datasets > 0 ? plural(datasets, 'dataset') : null, tables > 0 ? plural(tables, 'table') : null]
    const present = parts.filter((part): part is string => part !== null)
    return present.length > 0 ? present.join(', ') : 'None'
}

const TILE_LABELS: Partial<Record<ManagedWarehouseLandingStateEnumApi, string>> = {
    in_sync: 'In sync',
    behind: 'Behind',
    failing: 'Failing',
    not_in_warehouse: 'Not in warehouse yet',
}

/** The four tiles of the strip. Paused tables are not a tile: the In sync tile notes them. */
export function landingTiles(totals: LandingTotals): LandingTile[] {
    return (['in_sync', 'behind', 'failing', 'not_in_warehouse'] as const).map((state) => {
        const count = totals[state]
        const paused = totals.paused.tables
        return {
            state,
            label: TILE_LABELS[state] as string,
            value: formatCount(count.datasets + count.tables),
            detail: splitDetail(count),
            ...(state === 'in_sync' && paused > 0 ? { note: `${plural(paused, 'table')} paused` } : {}),
        }
    })
}

const joinWithAnd = (parts: string[]): string =>
    parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : (parts[0] ?? '')

/** One line on how much has not landed yet, or that everything has. */
export function landingSummary(totals: LandingTotals): { text: string; allLanded: boolean } {
    const count = (state: ManagedWarehouseLandingStateEnumApi): number => totals[state].datasets + totals[state].tables
    const parts = [
        count('behind') > 0 ? `${formatCount(count('behind'))} behind` : null,
        count('failing') > 0 ? `${formatCount(count('failing'))} failing` : null,
        count('not_in_warehouse') > 0 ? `${formatCount(count('not_in_warehouse'))} not landed` : null,
    ].filter((part): part is string => part !== null)
    return parts.length === 0
        ? { text: 'Everything has landed in your warehouse', allLanded: true }
        : { text: `${joinWithAnd(parts)} in your warehouse`, allLanded: false }
}

/** "Waiting 2 h 05 m" for an import still waiting for the warehouse, or null when nothing waits. */
export function waitingText(pendingSince: string | null | undefined, now: number = Date.now()): string | null {
    if (!pendingSince) {
        return null
    }
    return `Waiting ${formatDuration(Math.max(0, now - new Date(pendingSince).getTime()))}`
}

/** One bar per day. Source and backfill runs share a bar, and the tooltip note gives the split. */
export function historyBuckets(history: ManagedWarehouseLandingHistoryResponseApi): RunBucket[] {
    return history.buckets.map((bucket) => ({
        key: bucket.date,
        successful: bucket.source_succeeded + bucket.backfill_succeeded,
        failed: bucket.source_failed + bucket.backfill_failed,
        note: `sources: ${bucket.source_succeeded} succeeded, ${bucket.source_failed} failed; backfill: ${bucket.backfill_succeeded} succeeded, ${bucket.backfill_failed} failed`,
    }))
}

export function hasNoRuns(buckets: RunBucket[]): boolean {
    return buckets.every((bucket) => bucket.successful + bucket.failed === 0)
}

/** "12 / 14 in sync": the tables of a source that have landed, out of all of its tables. */
export function tablesInSync(source: ManagedWarehouseSourceSummaryApi): string {
    const total = LANDING_STATES.reduce((sum, state) => sum + source.landing_counts[state], 0)
    return `${formatCount(source.landing_counts.in_sync)} / ${formatCount(total)} in sync`
}

/** A calendar day such as 2026-11-20 as "Nov 20, 2026". */
export function formatDay(day: string): string {
    return dayjs(day).format('MMM D, YYYY')
}

/** A status the API sends as a lowercase token or a title ("Completed", "billing_limit") as plain words. */
export function humanizeStatus(status: string | null | undefined): string {
    if (!status) {
        return '-'
    }
    const words = status.replaceAll('_', ' ').toLowerCase()
    return words.charAt(0).toUpperCase() + words.slice(1)
}
