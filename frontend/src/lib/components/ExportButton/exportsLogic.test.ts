import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { ExportedAssetType, ExporterFormat, SidePanelTab } from '~/types'

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
    downloadExportedAsset: jest.fn().mockResolvedValue(true),
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
            expectsViewExportsButton: boolean
            expectsPanelOpen: boolean
        }[] = [
            {
                label: 'async export resolves to "Export started" and is tracked as undownloaded',
                response: asset({ id: 11, export_format: ExporterFormat.MP4, has_content: false }),
                format: ExporterFormat.MP4,
                settles: { resolved: 'Export started' },
                expectsDownload: false,
                freshIds: [11],
                expectsViewExportsButton: true,
                expectsPanelOpen: true,
            },
            {
                label: 'blocking export with content is downloaded and resolves to "Export complete!"',
                response: asset({ id: 12, export_format: ExporterFormat.CSV, has_content: true }),
                format: ExporterFormat.CSV,
                settles: { resolved: 'Export complete!' },
                expectsDownload: true,
                freshIds: [],
                expectsViewExportsButton: false,
                expectsPanelOpen: false,
            },
            {
                label: 'export that failed in the request rejects with the error',
                response: asset({ id: 13, export_format: ExporterFormat.MP4, exception: 'boom' }),
                format: ExporterFormat.MP4,
                settles: { rejected: 'Export failed: boom' },
                expectsDownload: false,
                freshIds: [],
                expectsViewExportsButton: true,
                expectsPanelOpen: false,
            },
            {
                label: 'create request that throws rejects with the error',
                rejectWith: new Error('network down'),
                format: ExporterFormat.MP4,
                settles: { rejected: 'Export failed: network down' },
                expectsDownload: false,
                freshIds: [],
                expectsViewExportsButton: true,
                expectsPanelOpen: false,
            },
        ]

        it.each(createCases)(
            '$label',
            async ({
                response,
                rejectWith,
                format,
                settles,
                expectsDownload,
                freshIds,
                expectsViewExportsButton,
                expectsPanelOpen,
            }) => {
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
                // Video renders finish out of band, so their kickoff toast must link to the exports panel.
                const toastOptions = jest.mocked(lemonToast.promise).mock.calls[0][2]
                expect(toastOptions?.button?.label).toEqual(expectsViewExportsButton ? 'View exports' : undefined)
                const runPromise = jest.mocked(lemonToast.promise).mock.calls[0][0]
                if ('resolved' in settles) {
                    await expect(runPromise).resolves.toBe(settles.resolved)
                } else {
                    await expect(runPromise).rejects.toThrow(settles.rejected)
                }
                expect(jest.mocked(downloadExportedAsset).mock.calls).toEqual(expectsDownload ? [[response]] : [])
                expect(logic.values.freshUndownloadedExports.map((a) => a.id)).toEqual(freshIds)
                // selectedTab is persisted across kea contexts, so assert the open+tab combination.
                expect(
                    sidePanelStateLogic.values.sidePanelOpen &&
                        sidePanelStateLogic.values.selectedTab === SidePanelTab.Exports
                ).toBe(expectsPanelOpen)
            }
        )

        it('does not confirm completion when the content download fails', async () => {
            // The export toast must not settle as "Export complete!" if retrieval failed — otherwise
            // the user sees success followed by a broken download (the reported black-screen symptom).
            jest.mocked(downloadExportedAsset).mockResolvedValueOnce(false)
            jest.spyOn(api.exports, 'create').mockResolvedValue(
                asset({ id: 14, export_format: ExporterFormat.PNG, has_content: true })
            )

            logic.actions.createExport({ exportData: { export_format: ExporterFormat.PNG } })
            await flush()

            // The export promise rejects instead of resolving to "Export complete!"...
            const runPromise = jest.mocked(lemonToast.promise).mock.calls[0][0]
            await expect(runPromise).rejects.toThrow('Export download failed')
            // ...and the generic failure toast is dismissed, since downloadExportedAsset
            // already surfaced the specific error.
            expect(lemonToast.dismiss).toHaveBeenCalled()
        })

        it('notifies once with a Download button that routes through downloadExport', async () => {
            const pending = asset({ id: 21, export_format: ExporterFormat.MP4, has_content: false })
            const finished = asset({ id: 21, export_format: ExporterFormat.MP4, has_content: true })
            // An unrelated completed export in the list must not trigger a toast of its own.
            const unrelated = asset({ id: 99, export_format: ExporterFormat.CSV, has_content: true })
            const downloadExportSpy = jest.spyOn(logic.actions, 'downloadExport')

            logic.actions.addFresh(pending)
            logic.actions.loadExportsSuccess([finished, unrelated])
            await flush()
            // A second poll of the same finished export must not re-toast it.
            logic.actions.loadExportsSuccess([finished, unrelated])
            await flush()

            expect(jest.mocked(lemonToast.success).mock.calls).toEqual([
                [
                    'Export complete!',
                    expect.objectContaining({ button: expect.objectContaining({ label: 'Download' }) }),
                ],
            ])
            // The export keeps its "not downloaded" highlight until the user actually downloads it.
            expect(logic.values.freshUndownloadedExports.map((a) => a.id)).toEqual([21])

            jest.mocked(lemonToast.success).mock.calls[0][1]!.button!.action()
            expect(downloadExportSpy).toHaveBeenCalledWith(finished)
        })

        it.each([
            {
                label: 'clears the highlight when the download succeeds',
                downloadOk: true,
                remainingIds: [] as number[],
            },
            { label: 'keeps the highlight when the download fails', downloadOk: false, remainingIds: [41] },
        ])('downloadExport $label', async ({ downloadOk, remainingIds }) => {
            const tracked = asset({ id: 41, export_format: ExporterFormat.MP4, has_content: true })
            logic.actions.addFresh(tracked)
            jest.mocked(downloadExportedAsset).mockResolvedValueOnce(downloadOk)

            logic.actions.downloadExport(tracked)
            await flush()

            expect(jest.mocked(downloadExportedAsset).mock.calls).toEqual([[tracked]])
            expect(logic.values.freshUndownloadedExports.map((a) => a.id)).toEqual(remainingIds)
        })

        it('surfaces the failure and stops tracking when a tracked async export fails', async () => {
            const pending = asset({ id: 22, export_format: ExporterFormat.MP4, has_content: false })
            const failed = asset({ id: 22, export_format: ExporterFormat.MP4, exception: 'render crashed' })

            logic.actions.addFresh(pending)
            logic.actions.loadExportsSuccess([failed])
            await flush()

            expect(lemonToast.error).toHaveBeenCalledWith('Export failed: render crashed')
            expect(logic.values.freshUndownloadedExports).toEqual([])
        })

        it('keeps polling a tracked export when its individual fetch fails', async () => {
            // A tracked export can be missing from a format-filtered list, so it is fetched directly.
            // A transient fetch failure must not stop the poll loop and orphan the export.
            jest.useFakeTimers()
            try {
                const pending = asset({ id: 31, export_format: ExporterFormat.MP4, has_content: false })
                // The list omits id 31 and its only entry is already complete, so a re-poll can
                // only come from the failed export being kept in the pending set.
                const unrelatedDone = asset({ id: 88, export_format: ExporterFormat.CSV, has_content: true })
                jest.spyOn(api.exports, 'get').mockRejectedValue(new Error('transient'))
                const loadExportsSpy = jest.spyOn(logic.actions, 'loadExports')

                logic.actions.addFresh(pending)
                logic.actions.loadExportsSuccess([unrelatedDone])
                await jest.advanceTimersByTimeAsync(30000)

                expect(api.exports.get).toHaveBeenCalledWith(31)
                expect(loadExportsSpy).toHaveBeenCalled()
                // The export is neither dropped nor prematurely notified as complete/failed.
                expect(logic.values.freshUndownloadedExports.map((a) => a.id)).toContain(31)
                expect(lemonToast.success).not.toHaveBeenCalled()
                expect(lemonToast.error).not.toHaveBeenCalled()
            } finally {
                jest.useRealTimers()
            }
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
