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
    window.URL.revokeObjectURL(objectURL)
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
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
}

export type TriggerExportProps = Pick<ExportedAssetType, 'export_format' | 'dashboard' | 'insight' | 'export_context'>
