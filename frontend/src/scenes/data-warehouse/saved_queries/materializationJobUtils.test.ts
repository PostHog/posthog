import { DataModelingJob } from '~/types'

import { computeJobDuration, jobLogsWindow } from './materializationJobUtils'

const START = '2024-01-10T10:00:00Z'
const START_PLUS_90S = '2024-01-10T10:01:30Z'

function makeJob(overrides: Partial<DataModelingJob>): DataModelingJob {
    return {
        id: 'job-1',
        saved_query_id: 'view-1',
        status: 'Completed',
        rows_materialized: 10,
        rows_expected: 10,
        error: null,
        created_at: START,
        last_run_at: START_PLUS_90S,
        workflow_id: 'wf',
        workflow_run_id: 'run-1',
        ...overrides,
    }
}

describe('materializationJobUtils', () => {
    // humanFriendlyDuration joins units with a non-breaking space
    const NINETY_SECONDS = '1m\u00a030s'

    test.each<[string, Partial<DataModelingJob>, string]>([
        ['running job', { status: 'Running' }, 'In progress'],
        ['completed job', {}, NINETY_SECONDS],
        [
            'failed job with stale last_run_at falls back to updated_at',
            { status: 'Failed', last_run_at: START, updated_at: START_PLUS_90S },
            NINETY_SECONDS,
        ],
        [
            'cancelled job stamped by a bulk update, where updated_at is the stale one',
            { status: 'Cancelled', last_run_at: START_PLUS_90S, updated_at: START },
            NINETY_SECONDS,
        ],
        ['failed job with stale last_run_at and no updated_at', { status: 'Failed', last_run_at: START }, '-'],
        ['unparseable created_at', { created_at: 'not-a-date' }, '-'],
        ['missing last_run_at on completed job', { last_run_at: undefined as unknown as string }, '-'],
    ])('computeJobDuration: %s', (_name, overrides, expected) => {
        expect(computeJobDuration(makeJob(overrides))).toEqual(expected)
    })

    test.each<[string, Partial<DataModelingJob>, string | undefined, string | undefined]>([
        [
            'completed job closes the window an hour after the run ended',
            {},
            '2024-01-10 10:00:00',
            '2024-01-10 11:01:30',
        ],
        ['running job leaves the window open', { status: 'Running' }, '2024-01-10 10:00:00', undefined],
        [
            'failed job uses updated_at for the window end',
            { status: 'Failed', last_run_at: START, updated_at: START_PLUS_90S },
            '2024-01-10 10:00:00',
            '2024-01-10 11:01:30',
        ],
        [
            'cancelled job stamped by a bulk update uses the fresher last_run_at',
            { status: 'Cancelled', last_run_at: START_PLUS_90S, updated_at: START },
            '2024-01-10 10:00:00',
            '2024-01-10 11:01:30',
        ],
        [
            'unparseable created_at omits dateFrom instead of sending "Invalid Date"',
            { created_at: 'not-a-date' },
            undefined,
            '2024-01-10 11:01:30',
        ],
    ])('jobLogsWindow: %s', (_name, overrides, expectedFrom, expectedTo) => {
        expect(jobLogsWindow(makeJob(overrides), 'UTC')).toEqual({ dateFrom: expectedFrom, dateTo: expectedTo })
    })
})
