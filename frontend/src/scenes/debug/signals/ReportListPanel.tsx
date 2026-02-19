import { useCallback, useEffect, useRef, useState } from 'react'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import { statusBadgeColor } from './helpers'
import type { ReportData, ReportListResponse } from './types'

const PAGE_SIZE = 20

export function ReportListPanel({
    selectedReportId,
    onSelectReport,
}: {
    selectedReportId: string | null
    onSelectReport: (reportId: string) => void
}): JSX.Element {
    const [reports, setReports] = useState<ReportData[]>([])
    const [loading, setLoading] = useState(false)
    const [loadingMore, setLoadingMore] = useState(false)
    const [hasMore, setHasMore] = useState(false)
    const [total, setTotal] = useState(0)
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState<string | null>(null)
    const [initialized, setInitialized] = useState(false)

    // Keep current statusFilter in a ref so fetchReports always reads the latest value
    const statusFilterRef = useRef(statusFilter)
    statusFilterRef.current = statusFilter

    const fetchReports = useCallback(async (offset: number, append: boolean) => {
        if (append) {
            setLoadingMore(true)
        } else {
            setLoading(true)
        }
        try {
            const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) })
            const currentStatus = statusFilterRef.current
            if (currentStatus) {
                params.set('status', currentStatus)
            }
            const response = await api.get<ReportListResponse>(
                `api/environments/@current/signals/list_reports/?${params.toString()}`
            )
            setReports((prev) => (append ? [...prev, ...response.results] : response.results))
            setHasMore(response.next !== null)
            setTotal(response.count)
            setInitialized(true)
        } catch {
            // silently fail — debug tool
        } finally {
            setLoading(false)
            setLoadingMore(false)
        }
    }, [])

    // Load on mount
    useEffect(() => {
        void fetchReports(0, false)
    }, [fetchReports])

    const handleRefresh = (): void => {
        void fetchReports(0, false)
    }

    const handleLoadMore = (): void => {
        void fetchReports(reports.length, true)
    }

    const handleStatusFilter = (s: string): void => {
        const next = s === 'all' ? null : s
        setStatusFilter(next)
        // Update the ref immediately so fetchReports picks it up
        statusFilterRef.current = next
        void fetchReports(0, false)
    }

    const filteredReports = search
        ? reports.filter(
              (r) =>
                  r.title?.toLowerCase().includes(search.toLowerCase()) ||
                  r.id.toLowerCase().includes(search.toLowerCase()) ||
                  r.status.toLowerCase().includes(search.toLowerCase())
          )
        : reports

    const statuses = ['all', 'ready', 'in_progress', 'candidate', 'pending_input', 'potential', 'failed']

    return (
        <div className="flex flex-col h-full border-r overflow-hidden" style={{ width: 300, minWidth: 300 }}>
            {/* Header */}
            <div className="shrink-0 p-2 space-y-2 border-b">
                <div className="flex items-center justify-between px-1">
                    <div className="font-semibold text-xs text-muted uppercase tracking-wide">
                        Reports{initialized ? ` (${total})` : ''}
                    </div>
                    <LemonButton size="xsmall" type="tertiary" onClick={handleRefresh}>
                        Refresh
                    </LemonButton>
                </div>
                <LemonInput
                    size="small"
                    placeholder="Filter by title or ID..."
                    value={search}
                    onChange={setSearch}
                    fullWidth
                />
                <div className="flex flex-wrap gap-1">
                    {statuses.map((s) => (
                        <button
                            key={s}
                            className={`text-[11px] px-1.5 py-0.5 rounded border cursor-pointer transition-colors ${
                                (s === 'all' && !statusFilter) || statusFilter === s
                                    ? 'bg-primary-highlight text-primary border-primary font-medium'
                                    : 'bg-surface-primary text-muted border-border hover:bg-surface-secondary'
                            }`}
                            onClick={() => handleStatusFilter(s)}
                        >
                            {s === 'all' ? 'All' : s.replace('_', ' ')}
                        </button>
                    ))}
                </div>
            </div>

            {/* List */}
            <div className="flex-1 overflow-y-auto">
                {loading && !loadingMore ? (
                    <div className="flex items-center justify-center py-8">
                        <Spinner />
                    </div>
                ) : filteredReports.length === 0 ? (
                    <div className="text-muted text-xs text-center py-8 px-3">
                        {initialized ? 'No reports found' : 'Loading...'}
                    </div>
                ) : (
                    <>
                        {filteredReports.map((report) => {
                            const isSelected = report.id === selectedReportId
                            return (
                                <div
                                    key={report.id}
                                    className={`px-3 py-2 cursor-pointer border-b transition-colors ${
                                        isSelected ? 'bg-primary-highlight' : 'hover:bg-surface-secondary'
                                    }`}
                                    onClick={() => onSelectReport(report.id)}
                                >
                                    <div className="flex items-center gap-1.5 mb-0.5">
                                        <span
                                            className={`text-[10px] font-medium rounded px-1 py-0.5 leading-none ${statusBadgeColor(report.status)}`}
                                        >
                                            {report.status}
                                        </span>
                                        <span className="text-muted text-[10px] ml-auto shrink-0">
                                            {report.signal_count} signal{report.signal_count !== 1 ? 's' : ''}
                                        </span>
                                    </div>
                                    <div className="text-[13px] font-medium truncate">
                                        {report.title || <span className="text-muted italic">Untitled</span>}
                                    </div>
                                    <div className="text-muted text-[11px] truncate font-mono">
                                        {report.id.slice(0, 8)}…
                                        {report.total_weight > 0 && (
                                            <span className="ml-1">· w{report.total_weight.toFixed(1)}</span>
                                        )}
                                    </div>
                                </div>
                            )
                        })}

                        {/* Load more */}
                        {hasMore && !search && (
                            <div className="p-2">
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    fullWidth
                                    center
                                    loading={loadingMore}
                                    onClick={handleLoadMore}
                                >
                                    Load more ({reports.length} of {total})
                                </LemonButton>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}
