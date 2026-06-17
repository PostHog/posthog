import { expectLogic } from 'kea-test-utils'

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

    describe('async export toast resolution', () => {
        let logic: ReturnType<typeof exportsLogic.build>

        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            logic = exportsLogic()
            logic.mount()
        })

        it.each([
            {
                label: 'success',
                finishedAsset: asset({ id: 5, export_format: ExporterFormat.MP4, has_content: true }),
                expectedToast: { fn: 'success' as const, message: 'Export complete!' },
                expectsDownload: true,
            },
            {
                label: 'error',
                finishedAsset: asset({ id: 7, export_format: ExporterFormat.MP4, exception: 'boom' }),
                expectedToast: { fn: 'error' as const, message: 'Export failed: boom' },
                expectsDownload: false,
            },
        ])(
            'resolves the per-export toast to $label once a tracked async export finishes',
            async ({ finishedAsset, expectedToast, expectsDownload }) => {
                logic.actions.addFresh(asset({ id: finishedAsset.id, export_format: ExporterFormat.MP4 }))

                await expectLogic(logic, () => {
                    logic.actions.loadExportsSuccess([finishedAsset])
                }).toFinishAllListeners()

                if (expectsDownload) {
                    expect(downloadExportedAsset).toHaveBeenCalledWith(finishedAsset)
                } else {
                    expect(downloadExportedAsset).not.toHaveBeenCalled()
                }
                expect(lemonToast.dismiss).toHaveBeenCalledWith(`export-${finishedAsset.id}`)
                expect(lemonToast[expectedToast.fn]).toHaveBeenCalledWith(expectedToast.message)
                expect(logic.values.freshUndownloadedExports).toEqual([])
            }
        )
    })
})
