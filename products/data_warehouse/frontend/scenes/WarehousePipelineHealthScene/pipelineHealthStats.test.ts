import type {
    ManagedWarehouseDatasetStatusApi,
    ManagedWarehouseDataStatusResponseApi,
    ManagedWarehouseLandingCountsApi,
    ManagedWarehouseLandingStateEnumApi,
    ManagedWarehouseSourceSummaryApi,
} from '../../generated/api.schemas'
import {
    formatDay,
    hasNoRuns,
    historyBuckets,
    humanizeStatus,
    landingSummary,
    landingTiles,
    landingTotals,
    tablesInSync,
    waitingText,
} from './pipelineHealthStats'

function dataset(landing_state: ManagedWarehouseLandingStateEnumApi): ManagedWarehouseDatasetStatusApi {
    return {
        dataset: 'events',
        readiness_state: 'up_to_date',
        detail: '',
        completed_partitions: 0,
        total_partitions: null,
        current_partition: null,
        last_updated_at: null,
        landing_state,
        failed_partitions: 0,
        last_error: null,
        last_completed_at: null,
        latest_day_loaded: null,
    }
}

function source(counts: Partial<ManagedWarehouseLandingCountsApi>): ManagedWarehouseSourceSummaryApi {
    const landing_counts = { in_sync: 0, behind: 0, failing: 0, not_in_warehouse: 0, paused: 0, ...counts }
    return {
        source_id: 's1',
        source_name: 'Stripe',
        source_type: 'Stripe',
        readiness_state: 'up_to_date',
        detail: '',
        total_schemas: 0,
        applied_schemas: 0,
        last_applied_at: null,
        last_synced_at: null,
        landing_state: 'in_sync',
        landing_counts,
        pending_since: null,
        sync_failed_schemas: 0,
    }
}

function status(
    events: ManagedWarehouseLandingStateEnumApi,
    persons: ManagedWarehouseLandingStateEnumApi,
    sources: ManagedWarehouseSourceSummaryApi[]
): ManagedWarehouseDataStatusResponseApi {
    return {
        overall_readiness_state: 'up_to_date',
        events: dataset(events),
        persons: dataset(persons),
        sources: { readiness_state: 'up_to_date', detail: '', sources },
        generated_at: '2026-11-24T10:00:00Z',
    } as ManagedWarehouseDataStatusResponseApi
}

describe('pipelineHealthStats', () => {
    it('counts datasets by their state and tables by every source, and words the tiles', () => {
        const totals = landingTotals(
            status('behind', 'in_sync', [
                source({ in_sync: 9, failing: 1, paused: 3 }),
                source({ in_sync: 5, not_in_warehouse: 2 }),
            ])
        )

        expect(landingTiles(totals)).toEqual([
            {
                state: 'in_sync',
                label: 'In sync',
                value: '15',
                detail: '1 dataset, 14 tables',
                note: '3 tables paused',
            },
            { state: 'behind', label: 'Behind', value: '1', detail: '1 dataset' },
            { state: 'failing', label: 'Failing', value: '1', detail: '1 table' },
            { state: 'not_in_warehouse', label: 'Not in warehouse yet', value: '2', detail: '2 tables' },
        ])
    })

    it('says None for an empty state and leaves out the paused note when nothing is paused', () => {
        const tiles = landingTiles(landingTotals(status('in_sync', 'in_sync', [])))

        expect(tiles[0]).toEqual({ state: 'in_sync', label: 'In sync', value: '2', detail: '2 datasets' })
        expect(tiles[1].detail).toBe('None')
    })

    it.each([
        [
            status('in_sync', 'in_sync', [source({ in_sync: 4, paused: 1 })]),
            'Everything has landed in your warehouse',
            true,
        ],
        [status('behind', 'in_sync', [source({ failing: 1 })]), '1 behind and 1 failing in your warehouse', false],
        [
            status('in_sync', 'in_sync', [source({ behind: 2, failing: 1, not_in_warehouse: 1 })]),
            '2 behind, 1 failing and 1 not landed in your warehouse',
            false,
        ],
    ])('summarizes landing as "%#"', (input, text, allLanded) => {
        expect(landingSummary(landingTotals(input))).toEqual({ text, allLanded })
    })

    it.each([
        [null, null],
        ['2026-11-24T09:00:00Z', 'Waiting 1 h 00 m'],
        // A clock slightly behind the server must not show a negative wait.
        ['2026-11-24T10:00:30Z', 'Waiting 0 ms'],
    ])('words the wait since %s as %s', (pendingSince, expected) => {
        expect(waitingText(pendingSince, Date.parse('2026-11-24T10:00:00Z'))).toBe(expected)
    })

    it('merges source and backfill runs into one bar and keeps the split in the note', () => {
        const buckets = historyBuckets({
            days: 7,
            buckets: [
                {
                    date: '2026-11-23',
                    source_succeeded: 8,
                    source_failed: 1,
                    backfill_succeeded: 4,
                    backfill_failed: 2,
                },
                {
                    date: '2026-11-24',
                    source_succeeded: 0,
                    source_failed: 0,
                    backfill_succeeded: 0,
                    backfill_failed: 0,
                },
            ],
        })

        expect(buckets[0]).toMatchObject({ key: '2026-11-23', successful: 12, failed: 3 })
        expect(buckets[0].note).toBe('sources: 8 succeeded, 1 failed; backfill: 4 succeeded, 2 failed')
        expect(hasNoRuns(buckets)).toBe(false)
        expect(hasNoRuns([buckets[1]])).toBe(true)
    })

    it('words a source table count, a day and a status', () => {
        expect(tablesInSync(source({ in_sync: 12, behind: 1, paused: 1 }))).toBe('12 / 14 in sync')
        expect(formatDay('2026-11-20')).toBe('Nov 20, 2026')
        expect(humanizeStatus('billing_limit')).toBe('Billing limit')
        expect(humanizeStatus(null)).toBe('-')
    })
})
