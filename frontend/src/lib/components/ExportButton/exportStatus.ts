import { ExportedAssetType, ExporterFormat } from '~/types'

const LONG_RUNNING_FORMATS = new Set<ExporterFormat>([ExporterFormat.MP4, ExporterFormat.WEBM, ExporterFormat.GIF])

export function isLongRunningExportFormat(format: ExporterFormat | undefined | null): boolean {
    return !!format && LONG_RUNNING_FORMATS.has(format)
}

export type ExportPendingStatus = 'rendering_video' | 'pending'

export function getExportPendingStatus(asset: ExportedAssetType): ExportPendingStatus | null {
    if (asset.has_content || asset.exception) {
        return null
    }
    if (isLongRunningExportFormat(asset.export_format)) {
        return 'rendering_video'
    }
    return 'pending'
}

export function getExportPendingLabel(asset: ExportedAssetType): string | null {
    const status = getExportPendingStatus(asset)
    if (status === 'rendering_video') {
        return 'Rendering video — usually takes several minutes'
    }
    if (status === 'pending') {
        return 'Preparing export…'
    }
    return null
}

// A whole-session video longer than this cannot render inside the rasterizer's time budget. The
// backend does not refuse such exports, so this check is what stops a doomed render from starting.
export const MAX_EXPORTABLE_RECORDING_SECONDS = 3 * 60 * 60

export function getVideoExportDisabledReason(recordingDurationMs: number | undefined): string | undefined {
    if (recordingDurationMs === undefined) {
        return undefined
    }
    if (recordingDurationMs / 1000 <= MAX_EXPORTABLE_RECORDING_SECONDS) {
        return undefined
    }
    const hours = MAX_EXPORTABLE_RECORDING_SECONDS / 3600
    return `This recording is longer than ${hours} hours, which is too long to export as one video. Use the clip button to export part of it.`
}

export const MISSING_STYLES_WARNING =
    "Some page styles couldn't be loaded, so this video may show an unstyled page. Play the recording in PostHog to see it with its styles."

// The renderer fetches each stylesheet of the recorded page again from our servers. A host that the user's
// browser can reach but our servers cannot leaves the video unstyled, while the export still succeeds.
export function getExportWarning(asset: ExportedAssetType): string | null {
    const context = asset.export_context
    if (!asset.has_content || !context || !('stylesheets_failed' in context)) {
        return null
    }
    const failed = context.stylesheets_failed ?? 0
    const requested = context.stylesheets_requested ?? 0
    if (failed === 0 || failed * 2 < requested) {
        return null
    }
    return MISSING_STYLES_WARNING
}

export function getExportDisabledReason(asset: ExportedAssetType): string | undefined {
    if (asset.exception) {
        return asset.exception
    }
    if (asset.has_content) {
        return undefined
    }
    if (isLongRunningExportFormat(asset.export_format)) {
        return 'Video export is still rendering — this usually takes several minutes'
    }
    return 'Export not ready yet'
}
