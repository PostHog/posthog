import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'
import { ExternalDataSourceSchema } from '~/types'

import {
    externalDataSourcesAddTableCreate,
    externalDataSourcesBulkUpdateSchemasPartialUpdate,
} from 'products/warehouse_sources/frontend/generated/api'

import { addTableFormErrors, addTableLogic, tableNameFromPath } from './addTableLogic'
import { sourceSettingsLogic } from './sourceSettingsLogic'

jest.mock('products/warehouse_sources/frontend/generated/api', () => ({
    ...jest.requireActual('products/warehouse_sources/frontend/generated/api'),
    externalDataSourcesAddTableCreate: jest.fn(),
    externalDataSourcesBulkUpdateSchemasPartialUpdate: jest.fn(),
}))

const mockAddTable = externalDataSourcesAddTableCreate as jest.Mock
const mockBulkUpdate = externalDataSourcesBulkUpdateSchemasPartialUpdate as jest.Mock

const CREATED_SCHEMA = { id: 'schema-1', name: 'events', should_sync: false } as ExternalDataSourceSchema

describe('tableNameFromPath', () => {
    it.each([
        { path: 'events', expected: 'events' },
        { path: 'raw/Event Logs/', expected: 'event_logs' },
        { path: 'raw/orders.csv', expected: 'orders' },
        { path: 'raw/orders.csv.gz', expected: 'orders' },
        { path: 'raw/orders.2026.parquet', expected: 'orders_2026' },
        { path: 's3://bucket/events/2026/*.parquet', expected: '_2026' },
        { path: 'events/**/*.parquet', expected: 'events' },
        { path: 'events/{a,b}/*.csv', expected: 'events' },
        { path: '2026', expected: '_2026' },
        { path: '--my--table--', expected: 'my_table' },
        { path: '*.parquet', expected: '' },
        { path: '', expected: '' },
    ])('derives "$expected" from "$path"', ({ path, expected }) => {
        expect(tableNameFromPath(path)).toBe(expected)
    })
})

describe('addTableFormErrors', () => {
    it.each([
        { name: '', path: 'a', errorOn: 'name' },
        { name: '1abc', path: 'a', errorOn: 'name' },
        { name: 'my-table', path: 'a', errorOn: 'name' },
        { name: 'ok_name', path: '  ', errorOn: 'path' },
        { name: 'ok_name', path: '', errorOn: 'path' },
    ])('flags $errorOn for name "$name" and path "$path"', ({ name, path, errorOn }) => {
        const errors = addTableFormErrors({ name, path })
        expect(errors[errorOn]).toBeTruthy()
        expect(errors[errorOn === 'name' ? 'path' : 'name']).toBeUndefined()
    })

    it('accepts a valid name and path', () => {
        expect(addTableFormErrors({ name: '_ok1', path: 'events' })).toEqual({ name: undefined, path: undefined })
    })
})

describe('addTableLogic', () => {
    let logic: ReturnType<typeof addTableLogic.build>
    let settingsLogic: ReturnType<typeof sourceSettingsLogic.build>
    let loadSource: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        settingsLogic = sourceSettingsLogic({ id: 'source-1' })
        settingsLogic.mount()
        loadSource = jest.spyOn(settingsLogic.actions, 'loadSource').mockImplementation((() => ({})) as any)
        mockAddTable.mockResolvedValue(CREATED_SCHEMA)
        mockBulkUpdate.mockResolvedValue([])
        logic = addTableLogic({ sourceId: 'source-1' })
        logic.mount()
        logic.actions.openAddTable()
    })

    afterEach(() => {
        logic.unmount()
        settingsLogic.unmount()
        jest.restoreAllMocks()
        jest.clearAllMocks()
    })

    it('opens with defaults', () => {
        expect(logic.values.isAddTableOpen).toBe(true)
        expect(logic.values.addTable).toEqual({
            name: '',
            path: '',
            file_format: 'infer',
            csv_allow_double_quotes: true,
            start_syncing: true,
        })
    })

    it('fills the name from the path until the name is edited', () => {
        logic.actions.setAddTableValue('path', 'raw/orders.csv')
        expect(logic.values.addTable.name).toBe('orders')

        logic.actions.editName('my_orders')
        logic.actions.setAddTableValue('path', 'raw/events/')
        expect(logic.values.addTable.name).toBe('my_orders')
        expect(logic.values.nameEdited).toBe(true)
    })

    it('autofills again after the modal is reopened', () => {
        logic.actions.editName('custom')
        logic.actions.closeAddTable()
        logic.actions.openAddTable()
        logic.actions.setAddTableValue('path', 'events/')
        expect(logic.values.addTable.name).toBe('events')
    })

    it('shows validation errors and does not call the API for an empty form', async () => {
        await expectLogic(logic, () => logic.actions.submitAddTable()).toDispatchActions(['submitAddTableFailure'])
        expect(mockAddTable).not.toHaveBeenCalled()
        expect(logic.values.addTableErrors).toMatchObject({
            name: expect.any(String),
            path: expect.any(String),
        })
    })

    it.each([
        { startSyncing: true, sourcePageOpen: true, expectedSyncCalls: 1 },
        { startSyncing: false, sourcePageOpen: true, expectedSyncCalls: 0 },
        { startSyncing: true, sourcePageOpen: false, expectedSyncCalls: 1 },
    ])(
        'adds the table (start syncing: $startSyncing, source page open: $sourcePageOpen)',
        async ({ startSyncing, sourcePageOpen, expectedSyncCalls }) => {
            if (!sourcePageOpen) {
                settingsLogic.unmount()
            }
            logic.actions.setAddTableValue('path', 'events/*.csv')
            logic.actions.setAddTableValues({
                file_format: 'csv',
                csv_allow_double_quotes: false,
                start_syncing: startSyncing,
            })
            expect(logic.values.addTable.name).toBe('events')

            await expectLogic(logic, () => logic.actions.submitAddTable()).toDispatchActions(['submitAddTableSuccess'])

            expect(mockAddTable).toHaveBeenCalledWith(expect.any(String), 'source-1', {
                name: 'events',
                path: 'events/*.csv',
                file_format: 'csv',
                csv_allow_double_quotes: false,
            })
            expect(logic.values.isAddTableOpen).toBe(false)
            expect(loadSource).toHaveBeenCalledTimes(sourcePageOpen ? 1 : 0)
            expect(mockBulkUpdate.mock.calls).toEqual(
                Array(expectedSyncCalls).fill([
                    expect.any(String),
                    'source-1',
                    { schemas: [{ id: 'schema-1', should_sync: true }] },
                ])
            )
            if (!sourcePageOpen) {
                settingsLogic.mount()
            }
        }
    )

    it.each(['name', 'path'])('sets the %s field error from the API', async (attr) => {
        mockAddTable.mockRejectedValue(new ApiError('Bad request', 400, undefined, { attr, detail: 'Nope' }))
        logic.actions.setAddTableValues({ path: 'events/', name: 'events' })

        await expectLogic(logic, () => logic.actions.submitAddTable()).toDispatchActions(['submitAddTableSuccess'])

        expect(logic.values.addTableAllErrors[attr]).toBe('Nope')
        expect(logic.values.isAddTableOpen).toBe(true)
        expect(loadSource).not.toHaveBeenCalled()
    })

    it('keeps the modal open and does not reload when the error has no field', async () => {
        mockAddTable.mockRejectedValue(new ApiError('Boom', 500, undefined, { detail: 'Server error' }))
        logic.actions.setAddTableValues({ path: 'events/', name: 'events' })

        await expectLogic(logic, () => logic.actions.submitAddTable()).toDispatchActions(['submitAddTableSuccess'])

        expect(logic.values.isAddTableOpen).toBe(true)
        expect(loadSource).not.toHaveBeenCalled()
    })
})
