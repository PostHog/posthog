import api from 'lib/api'

import { ExportedAssetType, InsightShortId } from '~/types'

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

    // Trigger the download synchronously so it runs inside the click's user gesture. Safari only
    // performs a programmatic download while transient activation is live (~5s from the click), so any
    // await before this point causes it to silently drop the download.
    const anchor = document.createElement('a')
    anchor.style.display = 'none'
    anchor.href = downloadUrl
    document.body.appendChild(anchor)
    anchor.click()
    // Removing the anchor synchronously after click() can cancel the download in Firefox — defer it,
    // matching downloadBlob and downloadFile in lib/utils/dom.ts.
    setTimeout(() => {
        document.body.removeChild(anchor)
    }, 0)
}

export type TriggerExportProps = Pick<
    ExportedAssetType,
    'export_format' | 'dashboard' | 'insight' | 'export_context'
> & {
    insightShortId?: InsightShortId
}
