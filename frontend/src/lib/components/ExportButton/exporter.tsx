import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { ExportedAssetType } from '~/types'

export function downloadBlob(content: Blob, filename: string): void {
    const anchor = document.createElement('a')
    anchor.style.display = 'none'
    const objectURL = window.URL.createObjectURL(content)
    anchor.href = objectURL
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    // Firefox can cancel the download if the anchor is removed (or the URL revoked) synchronously
    // after click() — defer both, matching downloadFile in lib/utils/dom.ts.
    setTimeout(() => {
        document.body.removeChild(anchor)
        window.URL.revokeObjectURL(objectURL)
    }, 0)
}

export async function exportedAssetBlob(asset: ExportedAssetType): Promise<Blob> {
    const downloadUrl = api.exports.determineExportUrl(asset.id)
    const response = await api.getResponse(downloadUrl)
    return await response.blob()
}

export async function downloadExportedAsset(asset: ExportedAssetType): Promise<boolean> {
    const downloadUrl = api.exports.determineExportUrl(asset.id)

    // Probe the content endpoint before navigating to it. If retrieval fails (e.g. an access-control
    // 404), the raw JSON error would otherwise render as a blank/black page. api.getResponse throws on
    // a non-2xx status, so we can surface an error toast and keep the user where they are. We read only
    // the headers and cancel the body — the anchor navigation below streams the actual download to disk
    // without buffering large files (e.g. video exports) in memory.
    try {
        const response = await api.getResponse(downloadUrl)
        await response.body?.cancel()
    } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        lemonToast.error('Export download failed: ' + message)
        return false
    }

    const anchor = document.createElement('a')
    anchor.style.display = 'none'
    anchor.href = downloadUrl
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
    return true
}

export type TriggerExportProps = Pick<ExportedAssetType, 'export_format' | 'dashboard' | 'insight' | 'export_context'>
