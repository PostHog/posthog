import type {
    ManagedWarehouseDatasetStatusApi,
    ManagedWarehouseDataStatusResponseApi,
    ManagedWarehouseLandingCountsApi,
    ManagedWarehouseLandingStateEnumApi,
    ManagedWarehouseSourceSummaryApi,
} from '../../generated/api.schemas'
import {
    formatDay,
    humanizeStatus,
    landingSummary,
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

    it('words a source table count, a day and a status', () => {
        expect(tablesInSync(source({ in_sync: 12, behind: 1, paused: 1 }))).toBe('12 / 14 in sync')
        expect(formatDay('2026-11-20')).toBe('Nov 20, 2026')
        expect(humanizeStatus('billing_limit')).toBe('Billing limit')
        expect(humanizeStatus(null)).toBe('-')
    })
})
