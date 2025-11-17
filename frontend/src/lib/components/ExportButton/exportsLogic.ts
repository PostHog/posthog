import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { TriggerExportProps, downloadBlob, downloadExportedAsset } from 'lib/components/ExportButton/exporter'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { delay } from 'lib/utils'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { cohortsModel } from '~/models/cohortsModel'
import { AnyDataNode } from '~/queries/schema/schema-general'
import {
    APIErrorType,
    CohortType,
    ExportContext,
    ExportedAssetType,
    ExporterFormat,
    LocalExportContext,
    SidePanelTab,
} from '~/types'

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
        setAssetFormat: (format: ExporterFormat | null) => ({ format }),
        setHasReachedExportFullVideoLimit: (hasReached: boolean) => ({ hasReached }),
        startReplayExport: (
            sessionRecordingId: string,
            format?: ExporterFormat,
            timestamp?: number,
            duration?: number,
            mode?: SessionRecordingPlayerMode,
            options?: {
                width?: number
                height?: number
                css_selector?: string
                filename?: string
            }
        ) => ({ sessionRecordingId, format, timestamp, duration, mode, options }),
        startHeatmapExport: (export_context: ExportContext) => ({ export_context }),
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
        assetFormat: [
            null as ExporterFormat | null,
            {
                setAssetFormat: (_, { format }) => format,
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
        hasReachedExportFullVideoLimit: [
            false,
            {
                setHasReachedExportFullVideoLimit: (_, { hasReached }) => hasReached,
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
                } catch {
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
            } catch {
                lemonToast.dismiss(toastId)
                lemonToast.error('Cohort save failed')
            }
        },
        setAssetFormat: () => {
            actions.loadExports()
        },
        startReplayExport: async ({
            sessionRecordingId,
            format = ExporterFormat.PNG,
            timestamp,
            duration = 5,
            mode = SessionRecordingPlayerMode.Screenshot,
            options,
        }) => {
            const exportData: TriggerExportProps = {
                export_format: format,
                export_context: {
                    session_recording_id: sessionRecordingId,
                    timestamp: timestamp,
                    css_selector: options?.css_selector || '.replayer-wrapper',
                    width: options?.width || 1400,
                    height: options?.height || 600,
                    filename: options?.filename || `replay-${sessionRecordingId}${timestamp ? `-t${timestamp}` : ''}`,
                    duration: duration,
                    mode: mode,
                },
            }

            actions.startExport(exportData)
        },
        startHeatmapExport: async ({ export_context }) => {
            const exportData: TriggerExportProps = {
                export_format: ExporterFormat.PNG,
                export_context: export_context,
            }

            actions.startExport(exportData)
        },
    })),

    loaders(({ values, actions }) => ({
        exports: [
            [] as ExportedAssetType[],
            {
                loadExports: async (_, breakpoint) => {
                    await breakpoint(100)
                    const params: Record<string, any> = {}

                    // Add format filter if set
                    const format = values.assetFormat
                    if (format) {
                        params.export_format = format
                    }

                    const response = await api.exports.list(undefined, params)
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

                            const currentExports = values.exports
                            const updatedExports = [response, ...currentExports.filter((e) => e.id !== response.id)]
                            actions.loadExportsSuccess(updatedExports)

                            // If this was a blocking export, we should download it now
                            if (response && response.has_content) {
                                await downloadExportedAsset(response)
                            } else if (response && response.exception) {
                                lemonToast.error('Export failed: ' + response.exception)
                            }
                        } catch (error) {
                            const apiError = error as { data?: APIErrorType }
                            // Show a survey when the user reaches the export limit
                            if (apiError?.data?.attr === 'export_limit_exceeded') {
                                actions.setHasReachedExportFullVideoLimit(true)
                                lemonToast.error(apiError?.data?.detail || 'You reached your export limit.', {
                                    button: {
                                        label: 'I want more',
                                        className: 'replay-export-limit-reached-button',
                                        action: () => {}, //we trigger the survey by clicking the button, but we need to keep the action for the toast to show
                                        dataAttr: 'export-limit-reached-button',
                                    },
                                })
                            } else {
                                const message = error instanceof Error ? error.message : String(error)
                                lemonToast.error('Export failed: ' + message)
                            }
                        }
                    })()

                    return [exportData]
                },
            },
        ],
    })),
])
