import api from 'lib/api'

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

export function downloadExportedAsset(asset: ExportedAssetType): void {
    const downloadUrl = api.exports.determineExportUrl(asset.id)
    const anchor = document.createElement('a')
    anchor.style.display = 'none'
    anchor.href = downloadUrl
    // Signal download intent so the browser treats this as a download rather than a navigation
    // (the server's Content-Disposition still supplies the filename). The click can land well
    // after the user's gesture on slow, blocking exports, so make the intent explicit.
    anchor.download = ''
    document.body.appendChild(anchor)
    anchor.click()
    // Defer removal so Firefox doesn't cancel the download, matching downloadBlob above.
    setTimeout(() => {
        document.body.removeChild(anchor)
    }, 0)
}

export type TriggerExportProps = Pick<ExportedAssetType, 'export_format' | 'dashboard' | 'insight' | 'export_context'>
