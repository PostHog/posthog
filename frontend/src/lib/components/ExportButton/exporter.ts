import api from 'lib/api'
import { delay } from 'lib/utils'
import posthog from 'posthog-js'
import { ExportedAssetType, ExporterFormat } from '~/types'
import { lemonToast } from '../lemonToast'

const POLL_DELAY_MS = 1000
const MAX_PNG_POLL = 10
const MAX_CSV_POLL = 60

async function downloadExportedAsset(asset: ExportedAssetType): Promise<void> {
    const downloadUrl = api.exports.determineExportUrl(asset.id)
    const res = await api.getRaw(downloadUrl)
    const blobObject = await res.blob()
    const blob = window.URL.createObjectURL(blobObject)
    const anchor = document.createElement('a')
    anchor.style.display = 'none'
    anchor.href = blob
    anchor.download = asset.filename
    document.body.appendChild(anchor)
    anchor.click()
    window.URL.revokeObjectURL(blob)
}

export type TriggerExportProps = Pick<ExportedAssetType, 'export_format' | 'dashboard' | 'insight' | 'export_context'>

export async function triggerExport(asset: TriggerExportProps): Promise<void> {
    const poller = new Promise(async (resolve, reject) => {
        const trackingProperties = {
            export_format: asset.export_format,
            dashboard: asset.dashboard,
            insight: asset.insight,
            export_context: asset.export_context,
            total_time_ms: 0,
        }
        const startTime = performance.now()

        try {
            let exportedAsset = await api.exports.create({
                export_format: asset.export_format,
                dashboard: asset.dashboard,
                insight: asset.insight,
                export_context: asset.export_context,
            })

            if (!exportedAsset.id) {
                reject('Missing export_id from response')
                return
            }

            let attempts = 0

            const maxPoll = asset.export_format === ExporterFormat.CSV ? MAX_CSV_POLL : MAX_PNG_POLL
            while (attempts < maxPoll) {
                attempts++

                if (exportedAsset.has_content) {
                    await downloadExportedAsset(exportedAsset)

                    trackingProperties.total_time_ms = performance.now() - startTime
                    posthog.capture('export succeeded', trackingProperties)

                    resolve('Export complete')
                    return
                }

                await delay(POLL_DELAY_MS)

                exportedAsset = await api.exports.get(exportedAsset.id)
            }

            reject('Content not loaded in time...')
        } catch (e: any) {
            trackingProperties.total_time_ms = performance.now() - startTime
            posthog.capture('export failed', trackingProperties)
            reject(`Export failed: ${JSON.stringify(e)}`)
        }
    })
    await lemonToast.promise(poller, {
        pending: 'Export started...',
        success: 'Export complete!',
        error: 'Export failed!',
    })
}
