import { ExportedAssetType, ExporterFormat } from '~/types'

import {
    getExportDisabledReason,
    getExportPendingLabel,
    getExportPendingStatus,
    isLongRunningExportFormat,
} from './exportStatus'

const baseAsset = (overrides: Partial<ExportedAssetType> = {}): ExportedAssetType => ({
    id: 1,
    export_format: ExporterFormat.CSV,
    has_content: false,
    filename: 'export.csv',
    created_at: '2026-05-11T19:00:00Z',
    ...overrides,
})

describe('exportStatus', () => {
    describe('isLongRunningExportFormat', () => {
        it.each([
            [true, ExporterFormat.MP4],
            [true, ExporterFormat.WEBM],
            [true, ExporterFormat.GIF],
            [false, ExporterFormat.PNG],
            [false, ExporterFormat.CSV],
            [false, ExporterFormat.PDF],
        ])('returns %s for format %s', (expected, format) => {
            expect(isLongRunningExportFormat(format)).toBe(expected)
        })

        it('returns false for missing format', () => {
            expect(isLongRunningExportFormat(undefined)).toBe(false)
            expect(isLongRunningExportFormat(null)).toBe(false)
        })
    })

    describe('getExportPendingStatus', () => {
        it('returns null when the asset has content', () => {
            expect(getExportPendingStatus(baseAsset({ has_content: true }))).toBeNull()
        })

        it('returns null when the asset has an exception', () => {
            expect(getExportPendingStatus(baseAsset({ exception: 'boom' }))).toBeNull()
        })

        it.each([ExporterFormat.MP4, ExporterFormat.WEBM, ExporterFormat.GIF])(
            'returns rendering_video for pending long-running format %s',
            (format) => {
                expect(getExportPendingStatus(baseAsset({ export_format: format }))).toBe('rendering_video')
            }
        )

        it('returns pending for other in-progress formats', () => {
            expect(getExportPendingStatus(baseAsset({ export_format: ExporterFormat.CSV }))).toBe('pending')
        })
    })

    describe('getExportPendingLabel', () => {
        it.each([ExporterFormat.MP4, ExporterFormat.WEBM, ExporterFormat.GIF])(
            'returns a video-specific message for %s',
            (format) => {
                expect(getExportPendingLabel(baseAsset({ export_format: format }))).toBe(
                    'Rendering video — usually takes several minutes'
                )
            }
        )

        it('returns a generic message for non-video pending exports', () => {
            expect(getExportPendingLabel(baseAsset({ export_format: ExporterFormat.CSV }))).toBe('Preparing export…')
        })

        it('returns null once the asset is ready', () => {
            expect(getExportPendingLabel(baseAsset({ has_content: true }))).toBeNull()
        })
    })

    describe('getExportDisabledReason', () => {
        it('surfaces the exception message when present', () => {
            expect(getExportDisabledReason(baseAsset({ exception: 'rasterize failed' }))).toBe('rasterize failed')
        })

        it('returns undefined when the asset is downloadable', () => {
            expect(getExportDisabledReason(baseAsset({ has_content: true }))).toBeUndefined()
        })

        it.each([ExporterFormat.MP4, ExporterFormat.WEBM, ExporterFormat.GIF])(
            'returns a video-specific reason for pending %s exports',
            (format) => {
                expect(getExportDisabledReason(baseAsset({ export_format: format }))).toBe(
                    'Video export is still rendering — this usually takes several minutes'
                )
            }
        )

        it('falls back to the generic reason for other formats', () => {
            expect(getExportDisabledReason(baseAsset({ export_format: ExporterFormat.PDF }))).toBe(
                'Export not ready yet'
            )
        })
    })
})
