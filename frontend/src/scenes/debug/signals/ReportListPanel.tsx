import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import { statusBadgeColor } from './helpers'
import { signalsDebugLogic } from './signalsDebugLogic'

export function ReportListPanel({
    selectedReportId,
    onSelectReport,
}: {
    selectedReportId: string | null
    onSelectReport: (reportId: string) => void
}): JSX.Element {
    const {
        filteredReports,
        reports,
        reportsTotal,
        reportsHasMore,
        reportsInitialized,
        reportsResponseLoading,
        moreReportsResponseLoading,
        reportSearch,
        statusFilter,
    } = useValues(signalsDebugLogic)

    const { setReportSearch, setStatusFilter, loadReports, loadMoreReports } = useActions(signalsDebugLogic)

    const [panelWidth, setPanelWidth] = useState(300)

    const statuses = ['all', 'ready', 'in_progress', 'candidate', 'pending_input', 'potential', 'failed']

    return (
        <ResizableElement
            defaultWidth={panelWidth}
            minWidth={200}
            maxWidth={600}
            onResize={setPanelWidth}
            className="flex flex-col h-full border-r overflow-hidden shrink-0"
            borderPosition="right"
        >
            {/* Header */}
            <div className="shrink-0 p-2 space-y-2 border-b">
                <div className="flex items-center justify-between px-1">
                    <div className="font-semibold text-xs text-muted uppercase tracking-wide">
                        Reports{reportsInitialized ? ` (${reportsTotal})` : ''}
                    </div>
                    <LemonButton size="xsmall" type="tertiary" onClick={() => loadReports()}>
                        Refresh
                    </LemonButton>
                </div>
                <LemonInput
                    size="small"
                    placeholder="Filter by title or ID..."
                    value={reportSearch}
                    onChange={setReportSearch}
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
                            onClick={() => setStatusFilter(s === 'all' ? null : s)}
                        >
                            {s === 'all' ? 'All' : s.replace('_', ' ')}
                        </button>
                    ))}
                </div>
            </div>

            {/* List */}
            <div className="flex-1 overflow-y-auto">
                {reportsResponseLoading && !moreReportsResponseLoading ? (
                    <div className="flex items-center justify-center py-8">
                        <Spinner />
                    </div>
                ) : filteredReports.length === 0 ? (
                    <div className="text-muted text-xs text-center py-8 px-3">
                        {reportsInitialized ? 'No reports found' : 'Loading...'}
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
                                    <div className="text-[13px] font-medium break-words">
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
                        {reportsHasMore && !reportSearch && (
                            <div className="p-2">
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    fullWidth
                                    center
                                    loading={moreReportsResponseLoading}
                                    onClick={loadMoreReports}
                                >
                                    Load more ({reports.length} of {reportsTotal})
                                </LemonButton>
                            </div>
                        )}
                    </>
                )}
            </div>
        </ResizableElement>
    )
}
