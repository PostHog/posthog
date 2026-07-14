import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'
import { ExportedAssetType, ExporterFormat } from '~/types'

import { downloadExportedAsset } from './exporter'
import { exportsLogic, pickPollDelayMs } from './exportsLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    // promise() passes the underlying promise straight through so the loader's side effects still run.
    lemonToast: {
        info: jest.fn(),
        success: jest.fn(),
        error: jest.fn(),
        dismiss: jest.fn(),
        promise: jest.fn((p) => p),
    },
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

        // Let the fire-and-forget IIFE in the createExport loader run to settlement.
        const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

        const createCases: {
            label: string
            response?: ExportedAssetType
            rejectWith?: Error
            format: ExporterFormat
            settles: { resolved: string } | { rejected: string }
            expectsDownload: boolean
            freshIds: number[]
        }[] = [
            {
                label: 'async export resolves to "Export started" and is tracked as undownloaded',
                response: asset({ id: 11, export_format: ExporterFormat.MP4, has_content: false }),
                format: ExporterFormat.MP4,
                settles: { resolved: 'Export started' },
                expectsDownload: false,
                freshIds: [11],
            },
            {
                label: 'blocking export with content is downloaded and resolves to "Export complete!"',
                response: asset({ id: 12, export_format: ExporterFormat.CSV, has_content: true }),
                format: ExporterFormat.CSV,
                settles: { resolved: 'Export complete!' },
                expectsDownload: true,
                freshIds: [],
            },
            {
                label: 'export that failed in the request rejects with the error',
                response: asset({ id: 13, export_format: ExporterFormat.MP4, exception: 'boom' }),
                format: ExporterFormat.MP4,
                settles: { rejected: 'Export failed: boom' },
                expectsDownload: false,
                freshIds: [],
            },
            {
                label: 'create request that throws rejects with the error',
                rejectWith: new Error('network down'),
                format: ExporterFormat.MP4,
                settles: { rejected: 'Export failed: network down' },
                expectsDownload: false,
                freshIds: [],
            },
        ]

        it.each(createCases)('$label', async ({ response, rejectWith, format, settles, expectsDownload, freshIds }) => {
            const createSpy = jest.spyOn(api.exports, 'create')
            if (rejectWith) {
                createSpy.mockRejectedValue(rejectWith)
            } else {
                createSpy.mockResolvedValue(response!)
            }

            logic.actions.createExport({ exportData: { export_format: format } })
            await flush()

            // The loading spinner is driven by lemonToast.promise, so the user always sees "Preparing export…".
            expect(lemonToast.promise).toHaveBeenCalledWith(
                expect.any(Promise),
                expect.objectContaining({ pending: 'Preparing export…' }),
                expect.objectContaining({ toastId: expect.any(String) })
            )
            const runPromise = jest.mocked(lemonToast.promise).mock.calls[0][0]
            if ('resolved' in settles) {
                await expect(runPromise).resolves.toBe(settles.resolved)
            } else {
                await expect(runPromise).rejects.toThrow(settles.rejected)
            }
            expect(jest.mocked(downloadExportedAsset).mock.calls).toEqual(expectsDownload ? [[response]] : [])
            expect(logic.values.freshUndownloadedExports.map((a) => a.id)).toEqual(freshIds)
        })

        it('replaces the failure toast with the upsell survey when the export limit is reached', async () => {
            jest.spyOn(api.exports, 'create').mockRejectedValue({
                data: { attr: 'export_limit_exceeded', detail: 'You hit the cap' },
            })

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.MP4 } })
            await flush()

            expect(logic.values.hasReachedExportFullVideoLimit).toBe(true)
            expect(lemonToast.dismiss).toHaveBeenCalled()
            expect(lemonToast.error).toHaveBeenCalledWith(
                'You hit the cap',
                expect.objectContaining({ button: expect.objectContaining({ label: 'I want more' }) })
            )
            expect(jest.mocked(downloadExportedAsset).mock.calls).toEqual([])
        })
    })
})
