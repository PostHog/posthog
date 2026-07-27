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
