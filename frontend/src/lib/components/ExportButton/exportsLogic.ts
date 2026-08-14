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

import {
    ExportNudgeCandidate,
    ExportNudgeSubject,
    captureExportNudgeCheckFailed,
    exportNudgeEventProperties,
    lookUpExportNudge,
    resolveExportNudgeEligibility,
} from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic'
import {
    ExportNudgeMessage,
    claimExportNudgeMessage,
} from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/ExportNudgeToast'

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

// The user gesture that started the export is still live, so an auto-download will fire. Falls back
// to true where navigator.userActivation is unavailable (older Firefox), which tolerates a delayed
// click anyway.
const isUserActivationLive = (): boolean => navigator.userActivation?.isActive ?? true

// A subscription delivers a rendered image, so only an export of one is worth answering with an
// offer of one. Someone taking a CSV wants the rows, and would be promised something else. The
// backend side of that fact is the PNG in products/exports/backend/temporal/subscriptions/
// activities.py's export asset, so if a subscription ever delivers another format, this follows.
const SUBSCRIBABLE_EXPORT_FORMATS: ExporterFormat[] = [ExporterFormat.PNG]

// Only a dashboard or a saved insight can be subscribed to, so every other export has no subject and
// is never nudged: a recording, a heatmap, a cohort, a data table, a billing report. An insight
// exported from a surface that does not pass its short id has no subscription page to offer either.
const exportNudgeSubject = (exportData: TriggerExportProps): ExportNudgeSubject | null => {
    if (!SUBSCRIBABLE_EXPORT_FORMATS.includes(exportData.export_format)) {
        return null
    }
    if (exportData.dashboard) {
        return { kind: 'dashboard', dashboardId: exportData.dashboard }
    }
    if (exportData.insightShortId) {
        return { kind: 'insight', insightShortId: exportData.insightShortId }
    }
    return null
}

interface ExportNudge {
    message: ExportNudgeMessage | null
    /** Only ever resolves to a candidate on the path where the check had to run. */
    late: Promise<ExportNudgeCandidate | null>
}

const NO_NUDGE: ExportNudge = { message: null, late: Promise.resolve(null) }

/**
 * Both scenes load the subject's subscriptions to render the subscribe button's count badge, so most
 * exports can answer eligibility on the spot and put the offer in their toast from the first frame.
 * The rest start the check here and fold it in when the export settles.
 */
const startExportNudge = (subject: ExportNudgeSubject | null): ExportNudge => {
    if (!subject) {
        return NO_NUDGE
    }
    const lookup = lookUpExportNudge(subject)
    if (lookup.status === 'ineligible') {
        return NO_NUDGE
    }
    if (lookup.status === 'eligible') {
        // Claimed here rather than when the export settles: the toast is about to render with the
        // offer in it, so it was shown even if the export then fails.
        return { message: claimExportNudgeMessage(lookup.candidate), late: Promise.resolve(null) }
    }
    return { message: null, late: resolveLateNudge(subject) }
}

// A stalled or failed check must never hold up the export's own feedback.
const resolveLateNudge = async (subject: ExportNudgeSubject): Promise<ExportNudgeCandidate | null> =>
    await withTimeout(resolveExportNudgeEligibility(subject), NUDGE_RESOLUTION_TIMEOUT_MS).catch((error) => {
        if (error instanceof PromiseTimeoutError) {
            // Every other failure reports its own step, so without this one a stalled check is
            // indistinguishable from an exporter who was simply ineligible.
            captureExportNudgeCheckFailed('timeout', exportNudgeEventProperties(subject))
        }
        return null
    })

// Only an undelivered file holds a toast open: while the export still owes the user something and
// the toast is carrying an offer, it waits to be clicked instead of closing on a timer.
const holdOpenFor = (message: ExportNudgeMessage | null, secondaryAction?: ToastButton): { autoClose?: false } =>
    message && secondaryAction ? { autoClose: false } : {}

interface ToastFrame {
    message: string | JSX.Element
    /** Empty where the offer lays the action out beside its own CTA, so it is not rendered twice. */
    button?: ToastButton
}

// Kept as one decision: the message and the button slot have to agree about who renders the action.
const toastFrame = (message: ExportNudgeMessage | null, headline: string, action?: ToastButton): ToastFrame =>
    message ? { message: message(headline, action) } : { message: headline, button: action }

/**
 * Folds a late offer into the toast the export has already settled into. Claiming happens here
 * rather than when the check answers: it reports an exposure, so an export that never renders the
 * offer, because it failed or because its toast is already gone, must not spend it.
 */
const foldNudgeIntoSettledToast = async (
    nudge: ExportNudge,
    toastId: string,
    headline: string,
    secondaryAction?: ToastButton
): Promise<void> => {
    const candidate = await nudge.late
    if (!candidate) {
        return
    }
    if (!lemonToast.isActive(toastId)) {
        // Recorded, otherwise a nudge dropped because its toast had closed is indistinguishable
        // from an exporter who was simply ineligible.
        captureExportNudgeCheckFailed('toast-gone', exportNudgeEventProperties(candidate.subject))
        return
    }
    const message = claimExportNudgeMessage(candidate)
    if (!message) {
        return
    }
    lemonToast.updateToSuccess(toastId, message(headline, secondaryAction), {
        ...holdOpenFor(message, secondaryAction),
    })
}

interface KickoffToast {
    toastId: string
    nudge: ExportNudge
}

/**
 * Settles a finished export onto a toast carrying its Download button: the one it is already on if
 * that is still up, a fresh one otherwise. Updating a dismissed id does nothing, and someone who
 * closed the spinner would be left with a file and nowhere to claim it from.
 */
const settleWithDownload = async (
    nudge: ExportNudge,
    existingToastId: string | null,
    onDownload: () => void
): Promise<void> => {
    const downloadButton = { label: 'Download', action: onDownload }
    const frame = toastFrame(nudge.message, EXPORT_COMPLETE_MESSAGE, downloadButton)
    const options = { button: frame.button, ...holdOpenFor(nudge.message, downloadButton) }

    if (existingToastId && lemonToast.isActive(existingToastId)) {
        lemonToast.updateToSuccess(existingToastId, frame.message, options)
        await foldNudgeIntoSettledToast(nudge, existingToastId, EXPORT_COMPLETE_MESSAGE, downloadButton)
        return
    }
    const toastId = 'export-complete-' + uuid()
    lemonToast.success(frame.message, { toastId, ...options })
    await foldNudgeIntoSettledToast(nudge, toastId, EXPORT_COMPLETE_MESSAGE, downloadButton)
}

/**
 * Hands a finished file over on a Download button, before any check: for a polled export this is the
 * only completion signal there is.
 */
const showExportCompleteToast = async (
    asset: ExportedAssetType,
    onDownload: () => void,
    kickoff?: KickoffToast
): Promise<void> => {
    // An export that acknowledged its kickoff already resolved its offer and, if it was eligible,
    // showed it. Reuse it rather than claiming a second time: the offer follows the export to the
    // toast it finishes on, for anyone who did not answer it while the render was running.
    const nudge =
        kickoff?.nudge ??
        // A polled export is identified by its asset, which carries no insight short id, so only a
        // dashboard can be nudged here. Insight exports finish inside their create request instead.
        startExportNudge(asset.dashboard ? { kind: 'dashboard', dashboardId: asset.dashboard } : null)
    await settleWithDownload(nudge, kickoff?.toastId ?? null, onDownload)
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
                    lemonToast.success(EXPORT_COMPLETE_MESSAGE)
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
            cache.exportKickoffToasts?.delete(exportedAsset.id)
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
                if (cache.notifiedExportIds.has(fresh.id)) {
                    continue
                }
                // Claimed before the fetch below, not after: this listener is dispatched by the poll
                // and by a finished create call, and two runs that both got past a check placed
                // after the await would each raise a completion toast for the same export.
                cache.notifiedExportIds.add(fresh.id)
                // The list can be format-filtered (assetFormat), so fetch directly if it's not in it.
                const listed = exportsList.find((asset) => asset.id === fresh.id)
                const customFetcher = cache.exportStatusFetchers?.get(fresh.id) as ExportStatusFetcher | undefined
                const latest = customFetcher
                    ? await customFetcher().catch(() => null)
                    : (listed ?? (await fetchExportOrNull(fresh.id)))
                if (!latest || isRendering(latest)) {
                    // Still rendering, or a transient fetch miss: release the claim so a later poll
                    // can notify, and keep an out-of-list export polling.
                    cache.notifiedExportIds.delete(fresh.id)
                    if (!listed) {
                        pending.push(latest ?? fresh)
                    }
                    continue
                }
                if (latest.has_content) {
                    cache.exportStatusFetchers?.delete(fresh.id)
                    const finished = latest
                    const kickoff = cache.exportKickoffToasts?.get(fresh.id)
                    cache.exportKickoffToasts?.delete(fresh.id)
                    // Not awaited: the nudge check must not delay the other exports in this batch,
                    // nor the next poll.
                    void showExportCompleteToast(finished, () => actions.downloadExport(finished), kickoff).catch(
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

    loaders(({ values, actions, cache }) => ({
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
                    // Video renders finish minutes later in the exports panel, so the kickoff toast
                    // must point somewhere instead of dead-ending. A synchronous export gets no such
                    // link: while it is pending its row does not exist client-side yet.
                    const viewExportsButton: ToastButton | undefined = isLongRunningExportFormat(
                        exportData.export_format
                    )
                        ? { label: 'View exports', action: () => actions.openSidePanel(SidePanelTab.Exports) }
                        : undefined
                    const nudge = startExportNudge(exportNudgeSubject(exportData))
                    // Set when a synchronous export finished but the create request outlived the
                    // click's user activation, so the download waits for a Download button, because
                    // Safari silently drops a programmatic download once activation has expired.
                    // Held on an object because runExport assigns it, and the checker reads a plain
                    // local in this scope as if that assignment never happened.
                    const awaiting: { download: ExportedAssetType | null } = { download: null }

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
                            // Not a failure, so not a rejection: the export succeeded and the file
                            // is ready, it just needs a fresh click. Rejecting here would settle the
                            // toast into its error frame on the way past.
                            awaiting.download = response
                            return EXPORT_COMPLETE_MESSAGE
                        }
                        if (response.exception) {
                            throw new Error('Export failed: ' + response.exception)
                        }
                        // Async export (e.g. video render) is a background job: acknowledge the
                        // kickoff and open the exports panel, where it lands once the render finishes.
                        actions.addFresh(response)
                        actions.openSidePanel(SidePanelTab.Exports)
                        cache.exportKickoffToasts ??= new Map<number, KickoffToast>()
                        cache.exportKickoffToasts.set(response.id, { toastId: exportToastId, nudge })
                        return 'Export started'
                    }

                    void (async () => {
                        try {
                            // The success frame is read when the toast settles, so an offer followed
                            // while the export was running is already gone by then, rather than
                            // being asked a second time.
                            const settledMessage: string = await lemonToast.promise(
                                runExport(),
                                {
                                    pending: toastFrame(nudge.message, EXPORT_PENDING_MESSAGE, viewExportsButton)
                                        .message,
                                    success: (data) =>
                                        toastFrame(nudge.message, data || EXPORT_COMPLETE_MESSAGE, viewExportsButton)
                                            .message,
                                    error: 'Export failed',
                                },
                                {
                                    toastId: exportToastId,
                                    button: toastFrame(nudge.message, EXPORT_PENDING_MESSAGE, viewExportsButton).button,
                                }
                            )
                            const readyForDownload = awaiting.download
                            if (readyForDownload) {
                                // This export is announced here, so the poll must not announce it
                                // again while it waits in freshUndownloadedExports to be clicked.
                                cache.notifiedExportIds ??= new Set<number>()
                                cache.notifiedExportIds.add(readyForDownload.id)
                                await settleWithDownload(nudge, exportToastId, () =>
                                    actions.downloadExport(readyForDownload)
                                )
                                return
                            }
                            await foldNudgeIntoSettledToast(nudge, exportToastId, settledMessage, viewExportsButton)
                        } catch (error) {
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
