import { MakeLogicType, actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { TriggerExportProps, downloadBlob, downloadExportedAsset } from 'lib/components/ExportButton/exporter'
import { isLongRunningExportFormat } from 'lib/components/ExportButton/exportStatus'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { ToastButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { PromiseTimeoutError, delay, withTimeout } from 'lib/utils/async'
import { uuid } from 'lib/utils/dom'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    ExportNudgeCandidate,
    captureExportNudgeCheckFailed,
    resolveExportNudgeEligibility,
} from 'scenes/dashboard/dashboardExportNudgeLogic'
import { ExportNudgeRenderer, claimExportNudgeMessage } from 'scenes/dashboard/DashboardExportNudgeToast'
import type { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
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

const POLL_DELAY_MS = 10000
// Long-running formats (e.g. MP4 session-replay renders) can take 30+ minutes,
// so polling every 10s produces unhelpful timeout noise. Back off when the
// pending queue is dominated by long-running formats.
const LONG_RUNNING_POLL_DELAY_MS = 30000
// Cap on the eligibility check; it normally answers long before the export lands.
const NUDGE_RESOLUTION_TIMEOUT_MS = 5000
const EXPORT_PENDING_MESSAGE = 'Preparing export…'
const EXPORT_COMPLETE_MESSAGE = 'Export complete!'

// An export is still rendering while it has neither produced content nor failed.
const isRendering = (asset: ExportedAssetType): boolean => !asset.has_content && !asset.exception

export type ExportStatusFetcher = () => Promise<ExportedAssetType | null>

const fetchExportOrNull = async (id: number): Promise<ExportedAssetType | null> => {
    try {
        return await api.exports.get(id)
    } catch {
        return null
    }
}

export const pickPollDelayMs = (pendingAssets: ExportedAssetType[]): number => {
    const pending = pendingAssets.filter(isRendering)
    if (pending.length === 0) {
        return POLL_DELAY_MS
    }
    return pending.every((asset) => isLongRunningExportFormat(asset.export_format))
        ? LONG_RUNNING_POLL_DELAY_MS
        : POLL_DELAY_MS
}

const isLocalExport = (context: ExportContext | undefined): context is LocalExportContext =>
    !!(context && 'localData' in context)

// Thrown when a synchronous export finished but the create request outlived the click's user
// activation, so the download must wait for a fresh gesture (a Download button) rather than
// auto-download — Safari silently drops programmatic downloads once activation has expired.
class ExportAwaitingDownload extends Error {
    constructor(public readonly asset: ExportedAssetType) {
        super('Export awaiting user download')
    }
}

// The user gesture that started the export is still live, so an auto-download will fire. Falls back
// to true where navigator.userActivation is unavailable (older Firefox), which tolerates a delayed
// click anyway.
const isUserActivationLive = (): boolean => navigator.userActivation?.isActive ?? true

// A stalled or failed check must never hold up the export's own feedback.
const settleNudgeCandidate = async (dashboardId: number | undefined): Promise<ExportNudgeCandidate | null> => {
    if (!dashboardId) {
        return null
    }
    return await withTimeout(resolveExportNudgeEligibility(dashboardId), NUDGE_RESOLUTION_TIMEOUT_MS).catch((error) => {
        if (error instanceof PromiseTimeoutError) {
            // Every other failure reports its own step, so without this one a stalled check is
            // indistinguishable from an exporter who was simply ineligible.
            captureExportNudgeCheckFailed('timeout', { dashboard_id: dashboardId })
        }
        return null
    })
}

interface ExportNudge {
    /** Null once the dashboard has no nudge to give, or once the check fails or outruns its deadline. */
    settled: Promise<ExportNudgeCandidate | null>
    /**
     * Claims where the nudge renders rather than when eligibility resolves, so an export that never
     * renders one does not spend it. Memoized: the same nudge renders under both of a toast's
     * headlines and must not count as two.
     */
    claim: (candidate: ExportNudgeCandidate | null) => ExportNudgeRenderer | null
}

const startExportNudge = (dashboardId: number | undefined, toastId: string): ExportNudge => {
    let claimed = false
    let reportedMissingToast = false
    let renderer: ExportNudgeRenderer | null = null
    return {
        settled: settleNudgeCandidate(dashboardId),
        claim: (resolved) => {
            if (!resolved) {
                return null
            }
            // Claiming spends the dashboard's one nudge and reports an exposure, so a toast the
            // user dismissed in the meantime must not claim.
            if (!lemonToast.isActive(toastId)) {
                if (!claimed && !reportedMissingToast) {
                    // Otherwise an eligible nudge dropped because its toast had already closed is
                    // indistinguishable from an exporter who was simply ineligible.
                    reportedMissingToast = true
                    captureExportNudgeCheckFailed('toast-gone', { dashboard_id: resolved.dashboardId })
                }
                return null
            }
            if (!claimed) {
                claimed = true
                renderer = claimExportNudgeMessage(resolved, toastId)
            }
            return renderer
        },
    }
}

/**
 * Folds the nudge into an export toast that has already settled, so a slow eligibility check never
 * delays the export's own feedback. A nudge asks for a decision, so it keeps the toast up until
 * dismissed and renders the toast's secondary action itself rather than showing it twice.
 */
const foldNudgeIntoToast = async (
    nudge: ExportNudge,
    toastId: string,
    headline: string,
    secondaryAction: ToastButton
): Promise<void> => {
    const renderer = nudge.claim(await nudge.settled)
    if (renderer) {
        lemonToast.updateToSuccess(toastId, renderer(headline, secondaryAction), { autoClose: false })
    }
}

const showExportCompleteToast = async (dashboardId: number | undefined, onDownload: () => void): Promise<void> => {
    const toastId = 'export-complete-' + uuid()
    const downloadButton = { label: 'Download', action: onDownload }
    // This is the only completion signal a polled export gets, so it is raised before the check.
    lemonToast.success(EXPORT_COMPLETE_MESSAGE, { toastId, button: downloadButton })
    await foldNudgeIntoToast(startExportNudge(dashboardId, toastId), toastId, EXPORT_COMPLETE_MESSAGE, downloadButton)
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface exportsLogicValues {
    assetFormat: ExporterFormat | null
    exports: ExportedAssetType[]
    exportsLoading: boolean
    freshUndownloadedExports: ExportedAssetType[]
    hasReachedExportFullVideoLimit: boolean
    pollingExports: ExportedAssetType[]
    pollingExportsLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface exportsLogicActions {
    openSidePanel: (
        tab: SidePanelTab,
        options?: string | undefined
    ) => {
        options: string | undefined
        tab: SidePanelTab
    } // sidePanelStateLogic
    addFresh: (exportedAsset: ExportedAssetType) => {
        exportedAsset: ExportedAssetType
    }
    createExport: ({ exportData }: any) => any
    createExportFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    createExportSuccess: (
        pollingExports: any[],
        payload?: any
    ) => {
        pollingExports: any[]
        payload?: any
    }
    createStaticCohort: (
        name: string,
        query: AnyDataNode
    ) => {
        name: string
        query: AnyDataNode
    }
    downloadExport: (exportedAsset: ExportedAssetType) => {
        exportedAsset: ExportedAssetType
    }
    loadExports: () => {
        value: true
    }
    loadExportsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadExportsSuccess: (
        exports: ExportedAssetType[],
        payload?: {
            value: true
        }
    ) => {
        exports: ExportedAssetType[]
        payload?: {
            value: true
        }
    }
    removeFresh: (exportedAsset: ExportedAssetType) => {
        exportedAsset: ExportedAssetType
    }
    setAssetFormat: (format: ExporterFormat | null) => {
        format: ExporterFormat | null
    }
    setHasReachedExportFullVideoLimit: (hasReached: boolean) => {
        hasReached: boolean
    }
    startExport: (exportData: TriggerExportProps) => {
        exportData: TriggerExportProps
    }
    startHeatmapExport: (export_context: ExportContext) => {
        export_context: ExportContext
    }
    startReplayExport: (
        sessionRecordingId: string,
        format?: ExporterFormat,
        timestamp?: number,
        duration?: number,
        mode?: SessionRecordingPlayerMode,
        options?: {
            css_selector?: string
            filename?: string
            height?: number
            skip_inactivity?: boolean
            width?: number
        }
    ) => {
        duration: number | undefined
        format: ExporterFormat | undefined
        mode: SessionRecordingPlayerMode | undefined
        options:
            | {
                  css_selector?: string | undefined
                  filename?: string | undefined
                  height?: number | undefined
                  skip_inactivity?: boolean | undefined
                  width?: number | undefined
              }
            | undefined
        sessionRecordingId: string
        timestamp: number | undefined
    }
    trackExport: (
        exportedAsset: ExportedAssetType,
        fetchLatest?: ExportStatusFetcher
    ) => {
        exportedAsset: ExportedAssetType
        fetchLatest: ExportStatusFetcher | undefined
    }
}

export type exportsLogicType = MakeLogicType<exportsLogicValues, exportsLogicActions>

export const exportsLogic = kea<exportsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'exportsLogic']),
    connect(() => ({
        actions: [sidePanelStateLogic, ['openSidePanel']],
    })),

    actions({
        loadExports: true,
        startExport: (exportData: TriggerExportProps) => ({ exportData }),
        addFresh: (exportedAsset: ExportedAssetType) => ({ exportedAsset }),
        trackExport: (exportedAsset: ExportedAssetType, fetchLatest?: ExportStatusFetcher) => ({
            exportedAsset,
            fetchLatest,
        }),
        removeFresh: (exportedAsset: ExportedAssetType) => ({ exportedAsset }),
        downloadExport: (exportedAsset: ExportedAssetType) => ({ exportedAsset }),
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
                skip_inactivity?: boolean
            }
        ) => ({ sessionRecordingId, format, timestamp, duration, mode, options }),
        startHeatmapExport: (export_context: ExportContext) => ({ export_context }),
    }),

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

    listeners(({ actions, values, cache }) => ({
        startExport: async ({ exportData }) => {
            // Fires for every dashboard export entry point (menu bar, dropdown, export button)
            // regardless of edit permission. Format is a property so PNG is filterable.
            if (exportData.dashboard && exportData.export_format) {
                eventUsageLogic.actions.reportDashboardExported(exportData.dashboard, exportData.export_format)
            }

            if (isLocalExport(exportData.export_context)) {
                try {
                    const blob = new Blob([exportData.export_context.localData], {
                        type: exportData.export_context.mediaType,
                    })
                    downloadBlob(blob, exportData.export_context.filename)
                    lemonToast.success('Export complete!')
                } catch (e: any) {
                    lemonToast.error(`Export failed with error: ${e.message}`)
                }
                return
            }

            actions.createExport({ exportData })
        },
        trackExport: ({ exportedAsset, fetchLatest }) => {
            cache.exportStatusFetchers ??= new Map<number, ExportStatusFetcher>()
            if (fetchLatest) {
                cache.exportStatusFetchers.set(exportedAsset.id, fetchLatest)
            }
            actions.setAssetFormat(null)
            actions.addFresh(exportedAsset)
            actions.openSidePanel(SidePanelTab.Exports)
        },
        removeFresh: ({ exportedAsset }) => {
            cache.exportStatusFetchers?.delete(exportedAsset.id)
        },
        createExportSuccess: () => {
            actions.loadExports()
        },
        downloadExport: ({ exportedAsset }) => {
            // Content already exists for this asset, so trigger the download synchronously — the click
            // has to run inside the user gesture or Safari silently drops it. Drop the "not downloaded"
            // highlight now that the download has been triggered.
            downloadExportedAsset(exportedAsset)
            actions.removeFresh(exportedAsset)
            lemonToast.success('Download started')
        },
        loadExportsSuccess: async ({ exports: exportsList }, breakpoint) => {
            // Surface async exports we kicked off that have now finished: the render completes long
            // after the kickoff toast, so this poll is the only completion signal the user gets.
            cache.notifiedExportIds ??= new Set<number>()
            const pending = exportsList.filter(isRendering)
            for (const fresh of values.freshUndownloadedExports) {
                // The list can be format-filtered (assetFormat), so fetch directly if it's not in it.
                const listed = exportsList.find((asset) => asset.id === fresh.id)
                const customFetcher = cache.exportStatusFetchers?.get(fresh.id) as ExportStatusFetcher | undefined
                const latest = customFetcher
                    ? await customFetcher().catch(() => null)
                    : (listed ?? (await fetchExportOrNull(fresh.id)))
                if (!latest || isRendering(latest)) {
                    // Still rendering, or a transient fetch miss: keep an out-of-list export polling.
                    if (!listed) {
                        pending.push(latest ?? fresh)
                    }
                    continue
                }
                if (cache.notifiedExportIds.has(fresh.id)) {
                    continue
                }
                if (latest.has_content) {
                    cache.exportStatusFetchers?.delete(fresh.id)
                    cache.notifiedExportIds.add(fresh.id)
                    const finished = latest
                    // Not awaited: the nudge check must not delay the other exports in this batch,
                    // nor the next poll.
                    void showExportCompleteToast(finished.dashboard, () => actions.downloadExport(finished)).catch(
                        (error) => posthog.captureException(error)
                    )
                } else {
                    actions.removeFresh(fresh)
                    lemonToast.error('Export failed: ' + latest.exception)
                }
            }

            if (pending.length) {
                await breakpoint(pickPollDelayMs(pending))
                actions.loadExports()
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
            options,
        }) => {
            const exportData: TriggerExportProps = {
                export_format: format,
                export_context: {
                    session_recording_id: sessionRecordingId,
                    timestamp: timestamp,
                    width: options?.width || 1400,
                    height: options?.height || 600,
                    filename: options?.filename || `replay-${sessionRecordingId}${timestamp ? `-t${timestamp}` : ''}`,
                    duration: duration,
                    skip_inactivity: options?.skip_inactivity ?? true,
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
                    const exportToastId = 'export-' + uuid()
                    // Every export lands in the exports panel, so every toast state points there.
                    const viewExportsButton = {
                        label: 'View exports',
                        action: () => actions.openSidePanel(SidePanelTab.Exports),
                    }
                    // Started at kickoff so its round trip overlaps the export itself, but never
                    // awaited by the export's own path.
                    const nudge = startExportNudge(exportData.dashboard, exportToastId)

                    // Non-video exports (CSV/XLSX/PNG) run synchronously on the backend, so this
                    // request can block for a while. lemonToast.promise shows a spinner immediately
                    // and swaps to the success/failure message when it settles, so the user always
                    // gets feedback instead of a menu that looks like it did nothing.
                    const runExport = async (): Promise<string> => {
                        let response: ExportedAssetType
                        try {
                            response = await api.exports.create({
                                export_format: exportData.export_format,
                                dashboard: exportData.dashboard,
                                insight: exportData.insight,
                                export_context: exportData.export_context,
                            })
                        } catch (error) {
                            // Preserve the export-limit error so the caller can show the upsell;
                            // give everything else a friendly message for the failure toast.
                            if ((error as { data?: APIErrorType })?.data?.attr === 'export_limit_exceeded') {
                                throw error
                            }
                            const message = error instanceof Error ? error.message : String(error)
                            throw new Error('Export failed: ' + message)
                        }

                        const currentExports = values.exports
                        const updatedExports = [response, ...currentExports.filter((e) => e.id !== response.id)]
                        actions.loadExportsSuccess(updatedExports)

                        if (response.has_content) {
                            // Blocking export already finished in the request. Auto-download while the
                            // click's activation is still live; if the create call outlived it (a slow
                            // synchronous render), Safari would drop the download, so hand off to a
                            // Download button whose click is a fresh gesture.
                            if (isUserActivationLive()) {
                                downloadExportedAsset(response)
                                return EXPORT_COMPLETE_MESSAGE
                            }
                            actions.addFresh(response)
                            throw new ExportAwaitingDownload(response)
                        }
                        if (response.exception) {
                            throw new Error('Export failed: ' + response.exception)
                        }
                        // Async export (e.g. video render) is a background job: acknowledge the
                        // kickoff and open the exports panel, where it lands once the render finishes.
                        actions.addFresh(response)
                        actions.openSidePanel(SidePanelTab.Exports)
                        return 'Export started'
                    }

                    const exportPromise = runExport()
                    let exportSettled = false
                    const markSettled = (): void => {
                        exportSettled = true
                    }
                    // Registered before lemonToast.promise, so `exportSettled` is already true by
                    // the time react-toastify queues the toast's own success or error render.
                    void exportPromise.then(markSettled, markSettled)

                    // A render takes seconds, so the pending frame is where the nudge has the most
                    // time to be read. Fire-and-forget: the export's own feedback never waits on it.
                    void nudge.settled
                        .then((candidate) => {
                            if (exportSettled) {
                                return
                            }
                            const renderer = nudge.claim(candidate)
                            if (renderer) {
                                lemonToast.updatePendingMessage(
                                    exportToastId,
                                    renderer(EXPORT_PENDING_MESSAGE, viewExportsButton)
                                )
                            }
                        })
                        .catch((error) => posthog.captureException(error))

                    void (async () => {
                        try {
                            // The nudge folds in under the headline the toast actually settled
                            // on: "Export started" for an async render, "Export complete!" for a
                            // synchronous one.
                            const settledMessage: string = await lemonToast.promise(
                                exportPromise,
                                {
                                    pending: EXPORT_PENDING_MESSAGE,
                                    success: EXPORT_COMPLETE_MESSAGE,
                                    error: 'Export failed',
                                },
                                // A failed export has nothing waiting in the panel, so the button
                                // rides only the pending and success frames.
                                { toastId: exportToastId, button: viewExportsButton, hideErrorButton: true }
                            )
                            await foldNudgeIntoToast(nudge, exportToastId, settledMessage, viewExportsButton)
                        } catch (error) {
                            if (error instanceof ExportAwaitingDownload) {
                                // Content is ready but the auto-download would have been dropped,
                                // so replace the spinner with a Download button the user can click.
                                // Rewritten in place so the nudge that follows lands on that toast.
                                const downloadButton = {
                                    label: 'Download',
                                    action: () => actions.downloadExport(error.asset),
                                }
                                lemonToast.updateToSuccess(exportToastId, EXPORT_COMPLETE_MESSAGE, {
                                    button: downloadButton,
                                })
                                await foldNudgeIntoToast(nudge, exportToastId, EXPORT_COMPLETE_MESSAGE, downloadButton)
                                return
                            }
                            const apiError = error as { data?: APIErrorType }
                            // Show a survey when the user reaches the export limit, replacing the
                            // generic failure toast with the upsell.
                            if (apiError?.data?.attr === 'export_limit_exceeded') {
                                lemonToast.dismiss(exportToastId)
                                actions.setHasReachedExportFullVideoLimit(true)
                                lemonToast.error(apiError?.data?.detail || 'You reached your export limit.', {
                                    autoClose: false,
                                    button: {
                                        label: 'I want more',
                                        className: 'replay-export-limit-reached-button',
                                        action: () => {}, //we trigger the survey by clicking the button, but we need to keep the action for the toast to show
                                        dataAttr: 'export-limit-reached-button',
                                    },
                                })
                            }
                        }
                    })()

                    return [exportData]
                },
            },
        ],
    })),
])
