import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'
import { ExportedAssetType, ExporterFormat } from '~/types'

import { downloadExportedAsset } from './exporter'
import { exportsLogic, pickPollDelayMs } from './exportsLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { info: jest.fn(), success: jest.fn(), error: jest.fn(), dismiss: jest.fn() },
}))
jest.mock('./exporter', () => ({
    ...jest.requireActual('./exporter'),
    downloadExportedAsset: jest.fn(),
}))

const asset = (overrides: Partial<ExportedAssetType> = {}): ExportedAssetType => ({
    id: 1,
    export_format: ExporterFormat.CSV,
    has_content: false,
    filename: 'export.csv',
    created_at: '2026-05-11T19:00:00Z',
    ...overrides,
})

describe('exportsLogic', () => {
    describe('pickPollDelayMs', () => {
        it('returns the default delay when nothing is pending', () => {
            expect(pickPollDelayMs([asset({ has_content: true })])).toBe(10000)
        })

        it('returns the default delay when at least one pending asset is fast', () => {
            expect(
                pickPollDelayMs([
                    asset({ id: 1, export_format: ExporterFormat.MP4 }),
                    asset({ id: 2, export_format: ExporterFormat.CSV }),
                ])
            ).toBe(10000)
        })

        it('backs off when every pending asset is a long-running format', () => {
            expect(
                pickPollDelayMs([
                    asset({ id: 1, export_format: ExporterFormat.MP4 }),
                    asset({ id: 2, export_format: ExporterFormat.WEBM }),
                ])
            ).toBe(30000)
        })

        it('ignores assets that already have content or an exception when deciding', () => {
            expect(
                pickPollDelayMs([
                    asset({ id: 1, export_format: ExporterFormat.CSV, has_content: true }),
                    asset({ id: 2, export_format: ExporterFormat.MP4 }),
                ])
            ).toBe(30000)
        })
    })

    describe('startReplayExport', () => {
        let logic: ReturnType<typeof exportsLogic.build>
        let startExportSpy: jest.SpyInstance

        beforeEach(() => {
            initKeaTests()
            logic = exportsLogic()
            logic.mount()
            startExportSpy = jest.spyOn(logic.actions, 'startExport')
        })

        afterEach(() => {
            startExportSpy.mockRestore()
        })

        it.each([
            { options: { skip_inactivity: true as const }, expected: true },
            { options: { skip_inactivity: false as const }, expected: false },
            { options: {}, expected: true },
        ])('sets skip_inactivity from export options', ({ options, expected }) => {
            logic.actions.startReplayExport('session-abc', ExporterFormat.MP4, 0, 3600, undefined, options)

            expect(startExportSpy).toHaveBeenCalledTimes(1)
            expect(startExportSpy.mock.calls[0][0].export_context?.skip_inactivity).toBe(expected)
        })
    })

    describe('createExport toast', () => {
        let logic: ReturnType<typeof exportsLogic.build>

        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            logic = exportsLogic()
            logic.mount()
            jest.spyOn(api.exports, 'list').mockResolvedValue({ results: [], count: 0 } as any)
        })

        afterEach(() => {
            logic.unmount()
        })

        // Let the fire-and-forget IIFE in the createExport loader run to its toast.
        const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

        it('acknowledges an async export immediately and tracks it as undownloaded', async () => {
            const asyncAsset = asset({ id: 11, export_format: ExporterFormat.MP4, has_content: false })
            jest.spyOn(api.exports, 'create').mockResolvedValue(asyncAsset)

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.MP4 } })
            await flush()

            expect(lemonToast.success).toHaveBeenCalledWith(
                'Export started',
                expect.objectContaining({ button: expect.any(Object) })
            )
            expect(downloadExportedAsset).not.toHaveBeenCalled()
            expect(logic.values.freshUndownloadedExports.map((a) => a.id)).toEqual([11])
        })

        it('downloads and confirms a blocking export that already has content', async () => {
            const doneAsset = asset({ id: 12, export_format: ExporterFormat.CSV, has_content: true })
            jest.spyOn(api.exports, 'create').mockResolvedValue(doneAsset)

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.CSV } })
            await flush()

            expect(downloadExportedAsset).toHaveBeenCalledWith(doneAsset)
            expect(lemonToast.success).toHaveBeenCalledWith('Export complete!')
            expect(logic.values.freshUndownloadedExports).toEqual([])
        })

        it('surfaces an export that failed during the request', async () => {
            const failedAsset = asset({ id: 13, export_format: ExporterFormat.MP4, exception: 'boom' })
            jest.spyOn(api.exports, 'create').mockResolvedValue(failedAsset)

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.MP4 } })
            await flush()

            expect(lemonToast.error).toHaveBeenCalledWith('Export failed: boom')
            expect(downloadExportedAsset).not.toHaveBeenCalled()
            expect(logic.values.freshUndownloadedExports).toEqual([])
        })
    })
})
