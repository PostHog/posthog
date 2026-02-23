import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { CountedPaginatedResponse } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { SignalReport } from 'scenes/inbox/types'

import { buildEdges } from './helpers'
import type { signalsDebugLogicType } from './signalsDebugLogicType'
import type { GraphEdge, SignalNode } from './types'

const REPORTS_PAGE_SIZE = 20

export const signalsDebugLogic = kea<signalsDebugLogicType>([
    path(['scenes', 'debug', 'signals', 'signalsDebugLogic']),

    actions({
        setReportId: (reportId: string) => ({ reportId }),
        selectReport: (reportId: string) => ({ reportId }),
        setSelectedSignalId: (signalId: string | null) => ({ signalId }),
        setHoveredEdge: (edge: GraphEdge | null) => ({ edge }),
        setMousePos: (pos: { x: number; y: number }) => ({ pos }),
        setReportSearch: (search: string) => ({ search }),
        setStatusFilter: (status: string | null) => ({ status }),
        loadMoreReports: true,
    }),

    loaders(({ values }) => ({
        reportSignalsResponse: [
            { report: null, signals: [] } as { report: SignalReport | null; signals: SignalNode[] },
            {
                loadReportSignals: async (reportId: string) => {
                    if (!reportId.trim()) {
                        return { report: null, signals: [] }
                    }
                    const response = await api.signalReports.getReportSignals(reportId.trim())
                    if (response.signals.length === 0) {
                        lemonToast.info('No signals found for this report')
                    }
                    return response
                },
            },
        ],
        reportsResponse: [
            { count: 0, results: [], next: null, previous: null } as CountedPaginatedResponse<SignalReport>,
            {
                loadReports: async () => {
                    const params: { limit: number; offset: number; status?: string } = {
                        limit: REPORTS_PAGE_SIZE,
                        offset: 0,
                    }
                    if (values.statusFilter) {
                        params.status = values.statusFilter
                    }
                    return await api.signalReports.listDebugReports(params)
                },
            },
        ],
        moreReportsResponse: [
            null as CountedPaginatedResponse<SignalReport> | null,
            {
                loadMoreReports: async () => {
                    const params: { limit: number; offset: number; status?: string } = {
                        limit: REPORTS_PAGE_SIZE,
                        offset: values.reports.length,
                    }
                    if (values.statusFilter) {
                        params.status = values.statusFilter
                    }
                    return await api.signalReports.listDebugReports(params)
                },
            },
        ],
    })),

    reducers({
        reportId: [
            '',
            {
                setReportId: (_, { reportId }) => reportId,
                selectReport: (_, { reportId }) => reportId,
            },
        ],
        selectedSignalId: [
            null as string | null,
            {
                setSelectedSignalId: (_, { signalId }) => signalId,
                // Clear selection when loading a new report
                loadReportSignals: () => null,
            },
        ],
        hoveredEdge: [
            null as GraphEdge | null,
            {
                setHoveredEdge: (_, { edge }) => edge,
                // Clear on new report load
                loadReportSignals: () => null,
            },
        ],
        mousePos: [
            { x: 0, y: 0 },
            {
                setMousePos: (_, { pos }) => pos,
            },
        ],
        reportSearch: [
            '',
            {
                setReportSearch: (_, { search }) => search,
            },
        ],
        statusFilter: [
            null as string | null,
            {
                setStatusFilter: (_, { status }) => status,
            },
        ],
        loaded: [
            false,
            {
                loadReportSignals: () => false,
                loadReportSignalsSuccess: () => true,
                loadReportSignalsFailure: () => false,
            },
        ],
    }),

    selectors({
        report: [(s) => [s.reportSignalsResponse], (response): SignalReport | null => response.report],
        signals: [(s) => [s.reportSignalsResponse], (response): SignalNode[] => response.signals],
        edges: [(s) => [s.signals], (signals): GraphEdge[] => buildEdges(signals)],
        rootIds: [
            (s) => [s.signals, s.edges],
            (signals, edges): Set<string> => {
                const childIds = new Set(edges.map((e) => e.target))
                return new Set(signals.filter((s) => !childIds.has(s.signal_id)).map((s) => s.signal_id))
            },
        ],
        selectedSignal: [
            (s) => [s.signals, s.selectedSignalId],
            (signals, selectedSignalId): SignalNode | null =>
                selectedSignalId ? (signals.find((s) => s.signal_id === selectedSignalId) ?? null) : null,
        ],
        reports: [(s) => [s.reportsResponse], (response): SignalReport[] => response.results],
        reportsTotal: [(s) => [s.reportsResponse], (response): number => response.count],
        reportsHasMore: [(s) => [s.reportsResponse], (response): boolean => response.next !== null],
        reportsInitialized: [
            (s) => [s.reportsResponseLoading, s.reportsResponse],
            (loading, response): boolean => !loading || response.results.length > 0,
        ],
        filteredReports: [
            (s) => [s.reports, s.reportSearch],
            (reports, search): SignalReport[] => {
                if (!search) {
                    return reports
                }
                const lower = search.toLowerCase()
                return reports.filter(
                    (r) =>
                        r.title?.toLowerCase().includes(lower) ||
                        r.id.toLowerCase().includes(lower) ||
                        r.status.toLowerCase().includes(lower)
                )
            },
        ],
        loading: [(s) => [s.reportSignalsResponseLoading], (loading): boolean => loading],
    }),

    listeners(({ actions, values }) => ({
        selectReport: ({ reportId }) => {
            actions.loadReportSignals(reportId)
        },
        setStatusFilter: () => {
            actions.loadReports()
        },
        loadMoreReportsSuccess: () => {
            // Append the new results to the existing response
            if (values.moreReportsResponse) {
                const combined: CountedPaginatedResponse<SignalReport> = {
                    ...values.moreReportsResponse,
                    results: [...values.reports, ...values.moreReportsResponse.results],
                }
                actions.loadReportsSuccess(combined)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadReports()
    }),
])
