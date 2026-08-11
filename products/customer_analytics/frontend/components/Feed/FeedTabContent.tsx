import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ReportCard } from 'products/signals/frontend/inbox/components/cards/ReportCard'

import { FeedFilterBar } from './FeedFilterBar'
import { feedLogic } from './feedLogic'

export function FeedTabContent(): JSX.Element {
    const { reports, reportsResponse, hasActiveFilters } = useValues(feedLogic)
    const { archiveReport, clearFilters } = useActions(feedLogic)

    return (
        <div className="flex flex-col gap-4">
            <FeedFilterBar />
            {reportsResponse === null ? (
                <LemonSkeleton className="h-64 w-full" />
            ) : reports.length === 0 ? (
                <div className="mx-auto max-w-md flex flex-col items-center text-center py-12 gap-2">
                    <h3 className="text-base font-semibold m-0">
                        {hasActiveFilters ? 'No reports match these filters' : 'No reports yet'}
                    </h3>
                    <p className="text-sm text-tertiary m-0">
                        {hasActiveFilters
                            ? 'Clear the filters to see every report from the customer analytics scouts.'
                            : 'The customer analytics scouts post reports here when they find account changes worth reviewing.'}
                    </p>
                    {hasActiveFilters && (
                        <LemonButton type="secondary" size="small" onClick={clearFilters}>
                            Clear filters
                        </LemonButton>
                    )}
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
