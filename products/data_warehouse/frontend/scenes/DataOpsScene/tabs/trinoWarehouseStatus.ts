import type {
    WarehouseStatusResponseApi,
    WarehouseStatusResponseStateEnumApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

export type TrinoCombinedState = WarehouseStatusResponseStateEnumApi | 'not_enabled' | 'unavailable'

export interface TrinoCombinedStatus {
    state: TrinoCombinedState
    message: string | null
    readyAt: string | null
    inProgress: boolean
}

const WAREHOUSE_IN_PROGRESS_STATES: WarehouseStatusResponseApi['state'][] = ['pending', 'provisioning', 'deleting']

// A Trino organization has two lifecycles: the warehouse and Trino on top of it. Users see one
// status, so Trino's state only matters once the warehouse itself is ready.
export function trinoCombinedStatus(status: WarehouseStatusResponseApi): TrinoCombinedStatus {
    if (status.state !== 'ready') {
        return {
            state: status.state,
            message: status.status_message || null,
            readyAt: null,
            inProgress: WAREHOUSE_IN_PROGRESS_STATES.includes(status.state),
        }
    }
    switch (status.trino?.state) {
        case 'ready':
            return { state: 'ready', message: null, readyAt: status.trino.ready_at ?? null, inProgress: false }
        case 'pending':
        case 'provisioning':
            return {
                state: 'provisioning',
                message: 'Setting up the query engine...',
                readyAt: null,
                inProgress: true,
            }
        case 'failed':
            return {
                state: 'failed',
                message: 'Query engine setup failed. Contact support.',
                readyAt: null,
                inProgress: false,
            }
        case 'not_enabled':
            return {
                state: 'not_enabled',
                message: "The query engine isn't set up for this warehouse yet. Contact support.",
                readyAt: null,
                inProgress: false,
            }
        default:
            return {
                state: 'unavailable',
                message: "Couldn't check the query engine status. Refresh to try again.",
                readyAt: null,
                inProgress: false,
            }
    }
}
