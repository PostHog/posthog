import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import * as api from 'products/data_warehouse/frontend/generated/api'
import type { StorageResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { warehouseProvisioningLogic } from '../DataOpsScene/tabs/warehouseProvisioningLogic'
import { describeMaintenance, tablePreviewUrl, warehouseStorageLogic } from './warehouseStorageLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    dataWarehouseWarehouseStatusRetrieve: jest.fn().mockResolvedValue(null),
    managedWarehouseConsoleStorageRetrieve: jest.fn(),
}))

function table(name: string, data_bytes: number, delete_bytes = 0): StorageResponseApi['tables'][number] {
    return {
        schema: 'main',
        table: name,
        data_bytes,
        delete_bytes,
        file_count: 1,
        row_count: 1,
        last_modified_at: null,
    }
}

describe('warehouseStorageLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('loads storage when it mounts after the status already resolved to ready', async () => {
        jest.mocked(api.dataWarehouseWarehouseStatusRetrieve).mockResolvedValue({
            state: 'ready',
            trino: { state: 'ready', hoglake: false, connection: null },
        } as never)
        jest.mocked(api.managedWarehouseConsoleStorageRetrieve).mockResolvedValue({
            tables: [],
            total_bytes: 0,
            pending_deletion_files: 0,
            read_at: null,
            maintenance: null,
        })
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]: true })
        const provisioning = warehouseProvisioningLogic()
        provisioning.mount()
        await expectLogic(provisioning).toDispatchActions(['loadWarehouseStatusSuccess'])

        const logic = warehouseStorageLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadStorageSuccess'])
    })

    it('sorts tables by size, counting delete files, and filters by search', () => {
        const logic = warehouseStorageLogic()
        logic.mount()
        logic.actions.loadStorageSuccess({
            tables: [table('events', 100), table('persons', 50, 80), table('sessions', 10)],
            total_bytes: 240,
            pending_deletion_files: 0,
            read_at: null,
            maintenance: null,
        })

        expect(logic.values.tableRows.map((row) => row.table)).toEqual(['persons', 'events', 'sessions'])
        logic.actions.setSearch('SESS')
        expect(logic.values.filteredTableRows.map((row) => row.qualified_name)).toEqual(['main.sessions'])
    })
})

describe('describeMaintenance', () => {
    it('lists scalar fields, flattens one nested level and skips lists', () => {
        expect(
            describeMaintenance({
                last_run_at: '2026-11-19T10:00:00Z',
                enabled: true,
                compaction: { files_merged: 12, errors: [] },
                tags: ['a'],
                empty: null,
            })
        ).toEqual([
            { label: 'Last run at', value: '2026-11-19T10:00:00Z' },
            { label: 'Enabled', value: 'Yes' },
            { label: 'Compaction files merged', value: '12' },
        ])
    })

    it('returns no fields for an unreadable status', () => {
        expect(describeMaintenance(null)).toEqual([])
    })
})

describe('tablePreviewUrl', () => {
    it('opens the managed Trino target with double quoted identifiers', () => {
        const url = decodeURIComponent(tablePreviewUrl('team_1', 'we"ird')).replaceAll('+', ' ')
        expect(url).toContain('SELECT * FROM "team_1"."we""ird" LIMIT 100')
        expect(url).toContain('managed_trino')
    })
})
