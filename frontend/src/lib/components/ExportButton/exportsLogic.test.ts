import { ExportedAssetType, ExporterFormat } from '~/types'

import { pickPollDelayMs } from './exportsLogic'

const asset = (overrides: Partial<ExportedAssetType> = {}): ExportedAssetType => ({
    id: 1,
    export_format: ExporterFormat.CSV,
    has_content: false,
    filename: 'export.csv',
    created_at: '2026-05-11T19:00:00Z',
    ...overrides,
})

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
