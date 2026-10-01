import type { WarehouseStatusResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { trinoCombinedStatus } from './trinoWarehouseStatus'

describe('trinoCombinedStatus', () => {
    const status = (
        state: WarehouseStatusResponseApi['state'],
        trinoState?: string,
        statusMessage = ''
    ): WarehouseStatusResponseApi =>
        ({
            state,
            status_message: statusMessage,
            trino: trinoState ? { state: trinoState, ready_at: '2026-09-01T12:00:00Z', connection: null } : null,
        }) as WarehouseStatusResponseApi

    it.each([
        {
            name: 'warehouse still provisioning',
            input: status('provisioning', 'pending', 'Creating storage'),
            expected: { state: 'provisioning', message: 'Creating storage', readyAt: null, inProgress: true },
        },
        {
            name: 'warehouse ready, Trino provisioning',
            input: status('ready', 'provisioning'),
            expected: {
                state: 'provisioning',
                message: 'Setting up the query engine...',
                readyAt: null,
                inProgress: true,
            },
        },
        {
            name: 'warehouse ready, Trino pending',
            input: status('ready', 'pending'),
            expected: {
                state: 'provisioning',
                message: 'Setting up the query engine...',
                readyAt: null,
                inProgress: true,
            },
        },
        {
            name: 'both ready',
            input: status('ready', 'ready'),
            expected: { state: 'ready', message: null, readyAt: '2026-09-01T12:00:00Z', inProgress: false },
        },
        {
            name: 'Trino failed',
            input: status('ready', 'failed'),
            expected: {
                state: 'failed',
                message: 'Query engine setup failed. Contact support.',
                readyAt: null,
                inProgress: false,
            },
        },
        {
            name: 'Trino not enabled',
            input: status('ready', 'not_enabled'),
            expected: {
                state: 'not_enabled',
                message: "The query engine isn't set up for this warehouse yet. Contact support.",
                readyAt: null,
                inProgress: false,
            },
        },
        {
            name: 'Trino status unavailable',
            input: status('ready', 'unavailable'),
            expected: {
                state: 'unavailable',
                message: "Couldn't check the query engine status. Refresh to try again.",
                readyAt: null,
                inProgress: false,
            },
        },
        {
            // The backend sends no trino block when its own variant check disagrees with the frontend's.
            name: 'Trino block missing',
            input: status('ready'),
            expected: {
                state: 'unavailable',
                message: "Couldn't check the query engine status. Refresh to try again.",
                readyAt: null,
                inProgress: false,
            },
        },
        {
            name: 'warehouse deleting',
            input: status('deleting', 'ready'),
            expected: { state: 'deleting', message: null, readyAt: null, inProgress: true },
        },
    ])('$name', ({ input, expected }) => {
        expect(trinoCombinedStatus(input)).toEqual(expected)
    })
})
