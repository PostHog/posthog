import type { WarehouseStatusResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { warehouseSettingsState } from './warehouseSettingsView'

function status(state: string, trinoState = 'ready', message = ''): WarehouseStatusResponseApi {
    return {
        state,
        status_message: message,
        ready_at: null,
        trino: { state: trinoState, ready_at: '2026-11-01T10:00:00Z', hoglake: false, connection: null },
    } as unknown as WarehouseStatusResponseApi
}

describe('warehouseSettingsState', () => {
    it.each([
        ['before the status answers', null, false, 'loading'],
        ['no warehouse', null, true, 'none'],
        ['a deleted warehouse', status('deleted'), true, 'none'],
        ['a failed provision', status('failed', 'not_enabled', 'Out of quota'), true, 'failed'],
        ['a warehouse provisioning', status('provisioning', 'pending'), true, 'in_progress'],
        ['a warehouse being deleted', status('deleting'), true, 'in_progress'],
        ['a ready warehouse whose engine is starting', status('ready', 'provisioning'), true, 'in_progress'],
        ['a ready warehouse with a failed engine', status('ready', 'failed'), true, 'ready'],
        ['a ready warehouse', status('ready'), true, 'ready'],
    ])('maps %s to the %s view', (_name, response, resolved, view) => {
        expect(warehouseSettingsState(response, resolved).view).toBe(view)
    })

    it('keeps the failure message and the ready time', () => {
        expect(warehouseSettingsState(status('failed', 'not_enabled', 'Out of quota'), true).message).toBe(
            'Out of quota'
        )
        expect(warehouseSettingsState(status('ready'), true).readyAt).toBe('2026-11-01T10:00:00Z')
    })
})
