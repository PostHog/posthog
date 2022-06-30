import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'
import { delay } from 'lib/utils'
import posthog from 'posthog-js'
import { ExportedAssetType } from '~/types'
import { lemonToast } from '../lemonToast'

import type { exporterLogicType } from './exporterLogicType'

const POLL_DELAY_MS = 1000
const MAX_POLL = 10

export interface ExporterLogicProps {
    dashboardId?: number
    insightId?: number
}

export enum ExporterFormat {
    PNG = 'image/png',
    CSV = 'text/csv',
    PDF = 'application/pdf',
}

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

export const exporterLogic = kea<exporterLogicType>([
    path(['lib', 'components', 'ExportButton', 'ExporterLogic']),
    props({} as ExporterLogicProps),
    key(({ dashboardId, insightId }) => {
        return `dash:${dashboardId}::insight:${insightId}`
    }),
    actions({
        exportItem: (
            exportFormat: ExporterFormat,
            exportContext?: Record<string, any>,
            successCallback?: () => void
        ) => ({ exportFormat, exportContext, successCallback }),
        exportItemSuccess: true,
        exportItemFailure: true,
    }),

    reducers({
        exportInProgress: [
            false,
            {
                exportItem: () => true,
                exportItemSuccess: () => false,
                exportItemFailure: () => false,
            },
        ],
    }),

    listeners(({ actions, props }) => ({
        exportItem: async ({ exportFormat, exportContext, successCallback }) => {
            lemonToast.info(`Export started...`)

            const trackingProperties = {
                export_format: exportFormat,
                dashboard: props.dashboardId,
                insight: props.insightId,
                total_time_ms: 0,
            }
            const startTime = performance.now()

            try {
                let exportedAsset = await api.exports.create({
                    export_format: exportFormat,
                    dashboard: props.dashboardId,
                    insight: props.insightId,
                    ...(exportContext || {}),
                })

                if (!exportedAsset.id) {
                    throw new Error('Missing export_id from response')
                }

                let attempts = 0

                while (attempts < MAX_POLL) {
                    attempts++

                    if (exportedAsset.has_content) {
                        actions.exportItemSuccess()
                        lemonToast.success(`Export complete.`)
                        successCallback?.()
                        await downloadExportedAsset(exportedAsset)

                        trackingProperties.total_time_ms = performance.now() - startTime
                        posthog.capture('export succeeded', trackingProperties)

                        return
                    }

                    await delay(POLL_DELAY_MS)

                    exportedAsset = await api.exports.get(exportedAsset.id)
                }

                throw new Error('Content not loaded in time...')
            } catch (e: any) {
                actions.exportItemFailure()
                trackingProperties.total_time_ms = performance.now() - startTime
                posthog.capture('export failed', trackingProperties)
                lemonToast.error(`Export failed: ${JSON.stringify(e)}`)
            }
        },
    })),
])
