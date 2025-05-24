import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { downloadBlob, downloadExportedAsset, TriggerExportProps } from 'lib/components/ExportButton/exporter'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { delay } from 'lib/utils'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { cohortsModel } from '~/models/cohortsModel'
import { AnyDataNode } from '~/queries/schema/schema-general'
import { CohortType, ExportContext, ExportedAssetType, LocalExportContext, SidePanelTab } from '~/types'

import type { exportsLogicType } from './exportsLogicType'

const POLL_DELAY_MS = 10000

const isLocalExport = (context: ExportContext | undefined): context is LocalExportContext =>
    !!(context && 'localData' in context)

export const exportsLogic = kea<exportsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'exportsLogic']),

    actions({
        loadExports: true,
        startExport: (exportData: TriggerExportProps) => ({ exportData }),
        checkExportStatus: (exportedAsset: ExportedAssetType) => ({ exportedAsset }),
        pollExportStatus: (exportedAsset: ExportedAssetType) => ({ exportedAsset }),
        addFresh: (exportedAsset: ExportedAssetType) => ({ exportedAsset }),
        removeFresh: (exportedAsset: ExportedAssetType) => ({ exportedAsset }),
        createStaticCohort: (name: string, query: AnyDataNode) => ({ query, name }),
    }),

    connect(() => ({
        actions: [sidePanelStateLogic, ['openSidePanel']],
    })),

    reducers({
        exports: [
            [] as ExportedAssetType[],
            {
                loadExportsSuccess: (_, { exports }) => exports,
            },
        ],
        freshUndownloadedExports: [
            [] as ExportedAssetType[],
            {
                addFresh: (state, { exportedAsset }) =>
                    state.some((asset) => asset.id === exportedAsset.id) ? state : [...state, exportedAsset],
                removeFresh: (state, { exportedAsset }) => state.filter((asset) => asset.id !== exportedAsset.id),
            },
        ],
    }),

    listeners(({ actions }) => ({
        startExport: async ({ exportData }) => {
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

            actions.createExport({ exportData })
        },
        createExportSuccess: () => {
            actions.openSidePanel(SidePanelTab.Exports)
            lemonToast.info('Export starting...')
            actions.loadExports()
        },
        loadExportsSuccess: async (_, breakpoint) => {
            // Check if any exports haven't completed
            const donePolling = exportsLogic.values.exports.every((asset) => asset.has_content || asset.exception)
            if (!donePolling) {
                await breakpoint(POLL_DELAY_MS)
                actions.loadExports()
                return
            }
        },
        createStaticCohort: async ({ query, name }) => {
            const toastId = 'toast-' + Math.random()
            try {
                lemonToast.info('Saving cohort...', { toastId, autoClose: false })
                const cohort: CohortType = await api.create('api/cohort', {
                    is_static: true,
                    name: name || 'Query cohort',
                    query: query,
                })
                cohortsModel.actions.cohortCreated(cohort)
                await delay(500) // just in case the toast is too fast
                lemonToast.dismiss(toastId)
                lemonToast.success('Cohort saved', {
                    toastId: `${toastId}-success`,
                    button: {
                        label: 'View cohort',
                        action: () => router.actions.push(urls.cohort(cohort.id)),
                    },
                })
            } catch (e) {
                lemonToast.dismiss(toastId)
                lemonToast.error('Cohort save failed')
            }
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
        pollingExports: [
            [] as ExportedAssetType[],
            {
                createExport: ({ exportData }) => {
                    void (async () => {
                        try {
                            const response = await api.exports.create({
                                export_format: exportData.export_format,
                                dashboard: exportData.dashboard,
                                insight: exportData.insight,
                                export_context: exportData.export_context,
                                expires_after: dayjs().add(6, 'hour').toJSON(),
                            })

                            const currentExports = exportsLogic.values.exports
                            const updatedExports = [response, ...currentExports.filter((e) => e.id !== response.id)]
                            exportsLogic.actions.loadExportsSuccess(updatedExports)

                            // If this was a blocking export, we should download it now
                            if (response && response.has_content) {
                                await downloadExportedAsset(response)
                            } else if (response && response.exception) {
                                lemonToast.error('Export failed: ' + response.exception)
                            }
                        } catch (error) {
                            const message = error instanceof Error ? error.message : String(error)
                            lemonToast.error('Export failed: ' + message)
                        }
                    })()

                    return [exportData]
                },
            },
        ],
    })),
])
