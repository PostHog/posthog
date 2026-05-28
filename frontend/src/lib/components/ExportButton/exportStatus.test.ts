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
            [ExporterFormat.MP4, true],
            [ExporterFormat.WEBM, true],
            [ExporterFormat.GIF, true],
            [ExporterFormat.PNG, false],
            [ExporterFormat.CSV, false],
            [ExporterFormat.PDF, false],
        ])('returns %s for %s', (format, expected) => {
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

        it('returns rendering_video for pending long-running formats', () => {
            expect(getExportPendingStatus(baseAsset({ export_format: ExporterFormat.MP4 }))).toBe('rendering_video')
        })

        it('returns pending for other in-progress formats', () => {
            expect(getExportPendingStatus(baseAsset({ export_format: ExporterFormat.CSV }))).toBe('pending')
        })
    })

    describe('getExportPendingLabel', () => {
        it('returns a video-specific message for MP4', () => {
            expect(getExportPendingLabel(baseAsset({ export_format: ExporterFormat.MP4 }))).toBe(
                'Rendering video — usually takes several minutes'
            )
        })

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

        it('returns a video-specific reason for pending MP4 exports', () => {
            expect(getExportDisabledReason(baseAsset({ export_format: ExporterFormat.MP4 }))).toBe(
                'Video export is still rendering — this usually takes several minutes'
            )
        })

        it('falls back to the generic reason for other formats', () => {
            expect(getExportDisabledReason(baseAsset({ export_format: ExporterFormat.PDF }))).toBe(
                'Export not ready yet'
            )
        })
    })
})
