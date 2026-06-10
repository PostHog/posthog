import { initKeaTests } from '~/test/init'
import { ExportedAssetType, ExporterFormat } from '~/types'

import { exportsLogic, pickPollDelayMs } from './exportsLogic'

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
})
