import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { warehouseTablesReplaceFileCreate } from 'products/data_warehouse/frontend/generated/api'
import type { TableApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { MAX_FILE_UPLOAD_SIZE_BYTES } from '../../NewSourceScene/fileUploadSourceLogic'
import { detectFileFormat, replaceFileLogic, replaceFileTarget } from './replaceFileLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    warehouseTablesReplaceFileCreate: jest.fn(),
}))

const mockReplace = warehouseTablesReplaceFileCreate as jest.MockedFunction<typeof warehouseTablesReplaceFileCreate>

const UPLOAD = { upload_id: 'upload-1', filename: 'orders.csv', file_format: 'csv', size_bytes: 3 }

function csvFile(name = 'orders.csv'): File {
    return new File(['a,b'], name)
}

describe('replaceFileLogic', () => {
    let logic: ReturnType<typeof replaceFileLogic.build>
    let uploadSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        uploadSpy = jest.spyOn(api.dataWarehouseTables, 'uploadFile').mockResolvedValue(UPLOAD)
        mockReplace.mockResolvedValue({ id: 'table-1', name: 'orders' } as TableApi)
        logic = replaceFileLogic({ sourceId: 'source-1' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
        uploadSpy.mockRestore()
    })

    it('uploads the file, replaces the table file and closes the modal', async () => {
        logic.actions.openReplaceFile({ tableId: 'table-1', tableName: 'orders', schemaId: 'schema-1' })
        logic.actions.selectFile(csvFile())

        await expectLogic(logic, () => {
            logic.actions.submitReplaceFile()
        }).toDispatchActions(['replaceFileSuccess', 'closeReplaceFile'])

        expect(mockReplace).toHaveBeenCalledWith(expect.any(String), 'table-1', {
            upload_id: 'upload-1',
            filename: 'orders.csv',
            file_format: 'csv',
        })
        expect(logic.values.isReplaceFileModalOpen).toBe(false)
        expect(logic.values.isReplacing).toBe(false)
    })

    it.each([
        {
            name: 'a linked table',
            schema: { table: { id: 'table-1', name: 'orders' }, table_id: 'table-1' },
            id: 'table-1',
        },
        { name: 'a table the schema only pins', schema: { table: undefined, table_id: 'table-9' }, id: 'table-9' },
        { name: 'a table without a table_id', schema: { table: { id: 'table-2', name: 'orders' } }, id: 'table-2' },
        { name: 'no table at all', schema: { table: undefined, table_id: null }, id: null },
    ])('targets the table id of $name', ({ schema, id }) => {
        expect(
            replaceFileTarget({ id: 'schema-1', name: 'orders', ...schema } as Parameters<typeof replaceFileTarget>[0])
                .tableId
        ).toBe(id)
    })

    it.each([
        {
            stage: 'upload',
            fail: (): void => {
                uploadSpy.mockRejectedValue({ status: 400, data: { message: 'Invalid filename' } })
            },
            message: 'Invalid filename',
        },
        {
            stage: 'replace',
            fail: (): void => {
                mockReplace.mockRejectedValue({
                    status: 400,
                    data: { message: 'A sync of this table is running. Replace the file once it finishes.' },
                })
            },
            message: 'A sync of this table is running. Replace the file once it finishes.',
        },
        {
            stage: 'replace without a table',
            fail: (): void => {},
            message: 'Could not find the table orders. Refresh the page and try again.',
        },
    ])('shows the API error and keeps the modal open when the $stage step fails', async ({ stage, fail, message }) => {
        fail()
        logic.actions.openReplaceFile({
            tableId: stage === 'replace without a table' ? null : 'table-1',
            tableName: 'orders',
            schemaId: 'schema-1',
        })
        logic.actions.selectFile(csvFile())

        await expectLogic(logic, () => {
            logic.actions.submitReplaceFile()
        }).toDispatchActions(['replaceFileFailure'])

        expect(logic.values.replaceError).toEqual(message)
        expect(logic.values.isReplaceFileModalOpen).toBe(true)
        expect(logic.values.isReplacing).toBe(false)
    })

    it('ignores a second submit while the first one is in flight', async () => {
        let releaseUpload: (value: typeof UPLOAD) => void = () => {}
        uploadSpy.mockReturnValue(new Promise<typeof UPLOAD>((resolve) => (releaseUpload = resolve)))
        logic.actions.openReplaceFile({ tableId: 'table-1', tableName: 'orders', schemaId: 'schema-1' })
        logic.actions.selectFile(csvFile())

        logic.actions.submitReplaceFile()
        logic.actions.submitReplaceFile()
        expect(logic.values.isReplacing).toBe(true)

        await expectLogic(logic, () => {
            releaseUpload(UPLOAD)
        }).toDispatchActions(['replaceFileSuccess'])

        expect(uploadSpy).toHaveBeenCalledTimes(1)
        expect(mockReplace).toHaveBeenCalledTimes(1)
    })

    it('does not submit a file the backend would refuse', () => {
        const oversized = csvFile()
        Object.defineProperty(oversized, 'size', { value: MAX_FILE_UPLOAD_SIZE_BYTES + 1 })
        logic.actions.openReplaceFile({ tableId: 'table-1', tableName: 'orders', schemaId: 'schema-1' })
        logic.actions.selectFile(oversized)

        logic.actions.submitReplaceFile()

        expect(logic.values.fileError).toContain('50MB')
        expect(uploadSpy).not.toHaveBeenCalled()
    })

    it.each([
        ['orders.csv', 'csv'],
        ['events.ndjson', 'json'],
        ['events.pqt', 'parquet'],
        ['export.txt', null],
        ['sheet.xlsx', null],
    ])('detects the format of %s as %s', (filename, expected) => {
        expect(detectFileFormat(filename)).toEqual(expected)
    })

    it('switches the format to match the chosen file', () => {
        logic.actions.selectFile(csvFile('events.parquet'))

        expect(logic.values.fileFormat).toEqual('parquet')
        expect(logic.values.fileError).toBeNull()
    })
})
