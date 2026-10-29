import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { warehouseTablesList, warehouseTablesReplaceFileCreate } from 'products/data_warehouse/frontend/generated/api'
import type { PaginatedTableListApi, TableApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { MAX_FILE_UPLOAD_SIZE_BYTES } from '../../NewSourceScene/fileUploadSourceLogic'
import { detectFileFormat, replaceFileLogic } from './replaceFileLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    warehouseTablesList: jest.fn(),
    warehouseTablesReplaceFileCreate: jest.fn(),
}))

const mockList = warehouseTablesList as jest.MockedFunction<typeof warehouseTablesList>
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
        logic.actions.openReplaceFile({ tableId: 'table-1', tableName: 'orders' })
        logic.actions.selectFile(csvFile())

        await expectLogic(logic, () => {
            logic.actions.submitReplaceFile()
        }).toDispatchActions(['replaceFileSuccess', 'closeReplaceFile'])

        expect(mockReplace).toHaveBeenCalledWith(expect.any(String), 'table-1', {
            upload_id: 'upload-1',
            filename: 'orders.csv',
            file_format: 'csv',
        })
        expect(mockList).not.toHaveBeenCalled()
        expect(logic.values.isReplaceFileModalOpen).toBe(false)
        expect(logic.values.isReplacing).toBe(false)
    })

    it('finds a table the source does not link to yet by its exact name', async () => {
        mockList.mockResolvedValue({
            count: 2,
            results: [
                { id: 'other', name: 'orders_backup' },
                { id: 'table-9', name: 'orders' },
            ],
        } as PaginatedTableListApi)
        logic.actions.openReplaceFile({ tableId: null, tableName: 'orders' })
        logic.actions.selectFile(csvFile())

        await expectLogic(logic, () => {
            logic.actions.submitReplaceFile()
        }).toDispatchActions(['replaceFileSuccess'])

        expect(mockReplace).toHaveBeenCalledWith(expect.any(String), 'table-9', expect.anything())
    })

    it('follows the result pages when the exact name is not on the first page', async () => {
        mockList
            .mockResolvedValueOnce({
                count: 2,
                next: 'next-page',
                results: [{ id: 'other', name: 'orders_backup' }],
            } as PaginatedTableListApi)
            .mockResolvedValueOnce({
                count: 2,
                next: null,
                results: [{ id: 'table-9', name: 'orders' }],
            } as PaginatedTableListApi)
        logic.actions.openReplaceFile({ tableId: null, tableName: 'orders' })
        logic.actions.selectFile(csvFile())

        await expectLogic(logic, () => {
            logic.actions.submitReplaceFile()
        }).toDispatchActions(['replaceFileSuccess'])

        expect(mockList).toHaveBeenCalledTimes(2)
        expect(mockList).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ offset: 1 }))
        expect(mockReplace).toHaveBeenCalledWith(expect.any(String), 'table-9', expect.anything())
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
            fail: (): void => {
                mockList.mockResolvedValue({ count: 0, results: [] } as PaginatedTableListApi)
            },
            message: 'Could not find the table orders. Refresh the page and try again.',
        },
    ])('shows the API error and keeps the modal open when the $stage step fails', async ({ stage, fail, message }) => {
        fail()
        logic.actions.openReplaceFile({
            tableId: stage === 'replace without a table' ? null : 'table-1',
            tableName: 'orders',
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
        logic.actions.openReplaceFile({ tableId: 'table-1', tableName: 'orders' })
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
        logic.actions.openReplaceFile({ tableId: 'table-1', tableName: 'orders' })
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
