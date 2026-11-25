import type { WarehouseStatusResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { trinoCombinedStatus } from '../DataOpsScene/tabs/trinoWarehouseStatus'
import type { TrinoCombinedState } from '../DataOpsScene/tabs/trinoWarehouseStatus'

/**
 * What the Settings page shows.
 * - loading: the status has not answered yet
 * - none: no warehouse, or one that was deleted, so the provision form shows
 * - failed: provisioning failed, so the form shows with a retry
 * - in_progress: the warehouse or its query engine is being set up or removed
 * - ready: the warehouse is serving
 */
export type WarehouseSettingsView = 'loading' | 'none' | 'failed' | 'in_progress' | 'ready'

export interface WarehouseSettingsState {
    view: WarehouseSettingsView
    /** The status users see: the warehouse and its query engine folded into one. */
    state: TrinoCombinedState | null
    message: string | null
    readyAt: string | null
}

export function warehouseSettingsState(
    status: WarehouseStatusResponseApi | null,
    resolved: boolean
): WarehouseSettingsState {
    if (!resolved) {
        return { view: 'loading', state: null, message: null, readyAt: null }
    }
    if (!status || status.state === 'deleted') {
        return { view: 'none', state: null, message: null, readyAt: null }
    }
    const combined = trinoCombinedStatus(status)
    const view: WarehouseSettingsView =
        status.state === 'failed' ? 'failed' : combined.inProgress ? 'in_progress' : 'ready'
    return {
        view,
        state: combined.state,
        message: combined.message ?? (status.state === 'failed' ? status.status_message || null : null),
        readyAt: combined.readyAt,
    }
}

export const WAREHOUSE_STATE_LABELS: Record<string, string> = {
    pending: 'Pending',
    provisioning: 'Provisioning',
    ready: 'Ready',
    failed: 'Failed',
    deleting: 'Deleting',
    not_enabled: 'Not enabled',
    unavailable: 'Unavailable',
}
