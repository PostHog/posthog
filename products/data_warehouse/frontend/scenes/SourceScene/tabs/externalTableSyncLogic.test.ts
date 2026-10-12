import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as api from 'products/data_warehouse/frontend/generated/api'
import type { ExternalTableSyncSettingsApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { externalTableSyncLogic } from './externalTableSyncLogic'

const SETTINGS: ExternalTableSyncSettingsApi = {
    available: true,
    unavailable_reason: null,
    enabled: false,
    interval_minutes: 60,
    status: 'disabled',
    last_synced_at: null,
    error: null,
}

describe('externalTableSyncLogic', () => {
    beforeEach(() => {
        useMocks({})
        initKeaTests()
    })

    afterEach(() => jest.restoreAllMocks())

    test.each([false, true])('guards duplicate saves and releases controls after failure=%s', async (fails) => {
        jest.spyOn(api, 'warehouseTablesWarehouseSyncRetrieve').mockResolvedValue(SETTINGS)
        let resolve!: (settings: ExternalTableSyncSettingsApi) => void
        let reject!: (error: Error) => void
        const pending = new Promise<ExternalTableSyncSettingsApi>((resolvePromise, rejectPromise) => {
            resolve = resolvePromise
            reject = rejectPromise
        })
        const save = jest.spyOn(api, 'warehouseTablesConfigureWarehouseSyncCreate').mockReturnValue(pending)
        const logic = externalTableSyncLogic({ tableId: '00000000-0000-0000-0000-000000000001' })
        logic.mount()
        try {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setEnabled(true)
            logic.actions.setIntervalMinutes(15)
            logic.actions.saveSettings()
            logic.actions.saveSettings()
            expect(logic.values.settingsLoading).toBe(true)
            expect(save).toHaveBeenCalledTimes(1)
            expect(save.mock.calls[0][2]).toEqual({ enabled: true, interval_minutes: 15 })
            if (fails) {
                reject(new Error('Save failed'))
            } else {
                resolve({ ...SETTINGS, enabled: true, interval_minutes: 15, status: 'preparing' })
            }
            await expectLogic(logic).toFinishAllListeners().toMatchValues({ settingsLoading: false })
            expect(logic.values.enabled).toBe(true)
            expect(logic.values.settings?.enabled).toBe(!fails)
        } finally {
            logic.unmount()
        }
    })
})
