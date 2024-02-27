import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { downloadBlob, downloadExportedAsset, TriggerExportProps } from 'lib/components/ExportButton/exporter'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { delay } from 'lib/utils'
import posthog from 'posthog-js'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ExportContext, ExportedAssetType, ExporterFormat, LocalExportContext, SidePanelTab } from '~/types'

import type { exportsLogicType } from './exportsLogicType'

const POLL_DELAY_MS = 1000
const MAX_PNG_POLL = 10
const MAX_CSV_POLL = 300

const isLocalExport = (context: ExportContext | undefined): context is LocalExportContext =>
    !!(context && 'localData' in context)

export const exportsLogic = kea<exportsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'exportsLogic']),

    actions({
        loadExports: true,
        createExport: (exportData: TriggerExportProps) => ({ exportData }),
        checkExportStatus: (exportedAsset: ExportedAssetType) => ({ exportedAsset }),
        pollExportStatus: (exportedAsset: ExportedAssetType) => ({ exportedAsset }),
    }),

    connect({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [sidePanelStateLogic, ['openSidePanel']],
    }),

    reducers({
        exports: [
            [] as ExportedAssetType[],
            {
                loadExportsSuccess: (_, { exports }) => exports,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        createExport: async ({ exportData }) => {
            if (isLocalExport(exportData.export_context)) {
                try {
                    downloadBlob(
                        new Blob([exportData.export_context.localData], { type: exportData.export_context.mediaType }),
                        exportData.export_context.filename
                    )
                    lemonToast.success('Export complete!')
                } catch (e) {
                    lemonToast.error('Export failed!')
                }
                return
            }

            const newExportedAsset = await api.exports.create({
                export_format: exportData.export_format,
                dashboard: exportData.dashboard,
                insight: exportData.insight,
                export_context: exportData.export_context,
                expires_after: dayjs().add(6, 'hour').toJSON(),
            })
            if (values.featureFlags[FEATURE_FLAGS.EXPORTS_SIDEPANEL]) {
                actions.openSidePanel(SidePanelTab.Exports)
            }
            actions.pollExportStatus(newExportedAsset)
        },
        pollExportStatus: async ({ exportedAsset }) => {
            // eslint-disable-next-line no-async-promise-executor,@typescript-eslint/no-misused-promises
            const poller = new Promise<string>(async (resolve, reject) => {
                const trackingProperties = {
                    export_format: exportedAsset.export_format,
                    dashboard: exportedAsset.dashboard,
                    insight: exportedAsset.insight,
                    export_context: exportedAsset.export_context,
                    total_time_ms: 0,
                }
                const startTime = performance.now()

                const maxPoll = exportedAsset.export_format === ExporterFormat.CSV ? MAX_CSV_POLL : MAX_PNG_POLL
                let updatedAsset = exportedAsset

                try {
                    let attempts = 0

                    while (attempts < maxPoll) {
                        attempts++

                        if (updatedAsset.has_content) {
                            if (values.featureFlags[FEATURE_FLAGS.EXPORTS_SIDEPANEL]) {
                                actions.loadExports()
                            }
                            // Download immediately if created within the last 5 seconds
                            if (dayjs().diff(dayjs(updatedAsset.created_at), 'second') < 5) {
                                void downloadExportedAsset(updatedAsset)
                            }

                            trackingProperties.total_time_ms = performance.now() - startTime
                            posthog.capture('export succeeded', trackingProperties)

                            resolve('Export complete')
                            return
                        }
                        await delay(POLL_DELAY_MS)

                        // Keep polling for pure network errors, but not any HTTP errors
                        // Example: `NetworkError when attempting to fetch resource`
                        try {
                            updatedAsset = await api.exports.get(exportedAsset.id)
                        } catch (e: any) {
                            if (e.name === 'NetworkError' || e.message?.message?.startsWith('NetworkError')) {
                                continue
                            }
                            throw e
                        }
                    }
                } catch (e: any) {
                    trackingProperties.total_time_ms = performance.now() - startTime
                    posthog.capture('export failed', trackingProperties)
                    reject(new Error(`Export failed: ${JSON.stringify(e.detail ?? e)}`))
                }
            })
            await lemonToast.promise(poller, {
                pending: 'Export starting...',
                success: 'Export complete!',
                error: 'Export failed!',
            })
        },
    })),

    loaders(() => ({
        exports: [
            [] as ExportedAssetType[],
            {
                loadExports: async (_, breakpoint) => {
                    await breakpoint(100)
                    const response = await api.exports.list()

                    breakpoint()

                    return response.results
                },
            },
        ],
    })),
])
