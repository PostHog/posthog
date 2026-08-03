import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { STATUS_LABELS } from 'scenes/inbox/components/badges/SignalReportStatusBadge'
import { ReportCard } from 'scenes/inbox/components/cards/ReportCard'
import { SignalReportStatus } from 'scenes/inbox/types'
import { urls } from 'scenes/urls'

import { feedLogic } from './feedLogic'

const STATUS_FILTER_OPTIONS: { value: SignalReportStatus | null; label: string }[] = [
    { value: null, label: 'Any status' },
    ...[
        SignalReportStatus.READY,
        SignalReportStatus.PENDING_INPUT,
        SignalReportStatus.IN_PROGRESS,
        SignalReportStatus.CANDIDATE,
        SignalReportStatus.POTENTIAL,
        SignalReportStatus.RESOLVED,
        SignalReportStatus.FAILED,
    ].map((status) => ({ value: status, label: STATUS_LABELS[status] ?? status })),
]

export function FeedTabContent(): JSX.Element {
    const { reports, reportsResponse, reportsResponseLoading, statusFilter, myReportsOnly } = useValues(feedLogic)
    const { setStatusFilter, setMyReportsOnly, archiveReport } = useActions(feedLogic)

    const filtersActive = statusFilter !== null || myReportsOnly

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center gap-4">
                <LemonSelect
                    size="small"
                    value={statusFilter}
                    onChange={setStatusFilter}
                    options={STATUS_FILTER_OPTIONS}
                    disabledReason={reportsResponseLoading ? 'Loading reports…' : undefined}
                    data-attr="customer-analytics-reports-status-filter"
                />
                <LemonCheckbox
                    checked={myReportsOnly}
                    onChange={setMyReportsOnly}
                    label="My reports"
                    info="Reports where you are a suggested reviewer"
                    disabledReason={reportsResponseLoading ? 'Loading reports…' : undefined}
                    data-attr="customer-analytics-reports-mine-filter"
                />
            </div>
            {reportsResponse === null ? (
                <LemonSkeleton className="h-64 w-full" />
            ) : reports.length === 0 ? (
                <div className="mx-auto max-w-md flex flex-col items-center text-center py-12 gap-2">
                    <h3 className="text-base font-semibold m-0">
                        {filtersActive ? 'No reports match these filters' : 'No reports yet'}
                    </h3>
                    <p className="text-sm text-tertiary m-0">
                        {filtersActive
                            ? 'Clear the filters to see every report from the customer analytics scouts.'
                            : 'The customer analytics scouts post reports here when they find account changes worth reviewing.'}
                    </p>
                </div>
            ) : (
                <div className="@container flex flex-col gap-1.5">
                    {reports.map((report) => (
                        <ReportCard
                            key={report.id}
                            report={report}
                            backUrl={urls.customerAnalyticsFeed()}
                            onArchive={(reason, note) => archiveReport(report.id, reason, note)}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
