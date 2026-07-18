import { BindLogic, useActions, useValues } from 'kea'
import { ComponentType, JSX, useEffect, useRef } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { captureInboxReportsImpressed, captureInboxViewed } from '../inboxAnalytics'
import { inboxSceneLogic } from '../inboxSceneLogic'
import { inboxFiltersLogic } from '../logics/inboxFiltersLogic'
import { reportListLogic, ReportListLogicProps } from '../logics/reportListLogic'
import { InboxFlatListTabKey, SignalReport } from '../types'
import { DismissalReasonValue } from '../utils/dismissalReasons'
import { CardSkeleton } from './cards/CardSkeleton'
import { InboxBulkSelectionBar } from './shell/InboxBulkSelectionBar'
import { InboxSearchFilterBar } from './shell/InboxSearchFilterBar'

export interface InboxReportCardProps {
    report: SignalReport
    tabKey: InboxFlatListTabKey
    onArchive: (reason: DismissalReasonValue, note: string) => void
    /** Restore a suppressed report back to the inbox. Only wired on the Archived tab. */
    onRestore?: () => void
    /** Rendered as an attached row inside a shared bordered container (vs. a freestanding card). */
    attached?: boolean
}

interface InboxReportListProps extends ReportListLogicProps {
    Card: ComponentType<InboxReportCardProps>
    emptyState: { icon: JSX.Element; title: string; description: string }
}

/**
 * Shared body for the three flat report-list tabs (Pull requests / Reports /
 * Not actionable). Each is the same primitive – only the `listParams` filter and
 * the empty-state copy differ. Binds the keyed `reportListLogic`, loads the first
 * page lazily on mount, shows a skeleton while a known-non-empty tab loads, and
 * appends pages via an IntersectionObserver sentinel.
 */
export function InboxReportList(props: InboxReportListProps): JSX.Element {
    return (
        <BindLogic logic={reportListLogic} props={{ tabKey: props.tabKey, listParams: props.listParams }}>
            <InboxReportListInner {...props} />
        </BindLogic>
    )
}

/** Sleek reminder that the list is filtered, with a one-click reset. Renders nothing when no filter is active. */
function ActiveFiltersBanner(): JSX.Element | null {
    const { hasActiveFilters } = useValues(inboxFiltersLogic)
    const { clearFilters } = useActions(inboxFiltersLogic)

    if (!hasActiveFilters) {
        return null
    }

    return (
        <LemonBanner type="info" action={{ children: 'Clear', onClick: () => clearFilters() }}>
            Filters are applied – some reports may be hidden.
        </LemonBanner>
    )
}

function InboxReportListInner({ tabKey, Card, emptyState }: InboxReportListProps): JSX.Element {
    const { reports, count, totalCount, hasMore, reportsResponseLoading, isLoaded, listApiParams } =
        useValues(reportListLogic)
    const { ensureLoaded, loadMore, archiveReport, restoreReport, refresh } = useActions(reportListLogic)
    const { hasActiveFilters, sourceProductFilter, priorityFilter, scope } = useValues(inboxFiltersLogic)
    // The list stays mounted (hidden) while a report/scout detail is open, so gate the view event on
    // the list actually being the visible surface — otherwise a deep-link to a report fires a phantom
    // `Inbox viewed` and then suppresses the real one when the user navigates back to the list.
    const { selectedReportId, selectedScoutSkillName, isScratchpadOpen, isFindingsOpen } = useValues(inboxSceneLogic)
    const listVisible = !selectedReportId && !selectedScoutSkillName && !isScratchpadOpen && !isFindingsOpen
    const sentinelRef = useRef<HTMLDivElement>(null)

    // Fire `Inbox viewed` once per tab mount, the first time its list settles while visible.
    const viewedFiredRef = useRef(false)
    useEffect(() => {
        if (listVisible && isLoaded && count !== null && !viewedFiredRef.current) {
            viewedFiredRef.current = true
            captureInboxViewed({
                tab: tabKey,
                reports,
                totalCount: count,
                hasActiveFilters,
                sourceProductFilter,
                priorityFilter,
                scope,
            })
        }
    }, [listVisible, isLoaded, count, reports, tabKey, hasActiveFilters, sourceProductFilter, priorityFilter, scope])

    // Impression log for ranking-model training: record each report the first time it appears in
    // the visible list (initial page, pagination, refresh), with its rank at that moment. Deduped
    // per tab mount so re-renders and detail-pane round-trips don't refire.
    const impressedIdsRef = useRef(new Set<string>())
    // Dedupe is per query: a sort/search/filter/scope change is a new ranking context, so a report
    // re-shown under the new query must impress again (at its new rank) for its later open/action
    // events to have a matching impression.
    const impressionQueryKeyRef = useRef('')
    useEffect(() => {
        // totalCount comes from the same response as `reports` (not the separately-loaded badge
        // count), so impressions can't be stamped with a total from a previous filter/refresh.
        if (!listVisible || !isLoaded || totalCount === null) {
            return
        }
        const queryKey = JSON.stringify(listApiParams)
        if (queryKey !== impressionQueryKeyRef.current) {
            impressionQueryKeyRef.current = queryKey
            impressedIdsRef.current = new Set<string>()
        }
        const fresh = reports
            .map((report, index) => ({ report, rank: index + 1 }))
            .filter(({ report }) => !impressedIdsRef.current.has(report.id))
        if (fresh.length === 0) {
            return
        }
        fresh.forEach(({ report }) => impressedIdsRef.current.add(report.id))
        captureInboxReportsImpressed({
            tab: tabKey,
            reports: fresh.map(({ report }) => report),
            ranks: fresh.map(({ rank }) => rank),
            listSize: reports.length,
            totalCount,
            hasActiveFilters,
            scope,
        })
    }, [listVisible, isLoaded, totalCount, reports, tabKey, hasActiveFilters, scope, listApiParams])

    // Read fresh state at intersection time via refs so the observer is created once and not
    // rebuilt twice per page fetch (`hasMore`/`reportsResponseLoading` both flip during a load).
    const hasMoreRef = useRef(hasMore)
    hasMoreRef.current = hasMore
    const loadingRef = useRef(reportsResponseLoading)
    loadingRef.current = reportsResponseLoading

    useEffect(() => {
        ensureLoaded()
    }, [ensureLoaded])

    useEffect(() => {
        const el = sentinelRef.current
        if (!el) {
            return
        }
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries[0]?.isIntersecting && hasMoreRef.current && !loadingRef.current) {
                    loadMore()
                }
            },
            // Generous prefetch margin so the next page lands well before the user reaches the bottom.
            { rootMargin: '1500px' }
        )
        observer.observe(el)
        return () => observer.disconnect()
    }, [loadMore])

    // Skeleton while a tab we know is non-empty loads its first page.
    const showSkeleton = !isLoaded && (reportsResponseLoading || (count ?? 0) > 0)

    return (
        <div className="@container mx-auto max-w-4xl flex flex-col gap-4 px-6 py-4">
            <InboxSearchFilterBar onRefresh={() => refresh()} refreshing={reportsResponseLoading} />
            <ActiveFiltersBanner />
            <InboxBulkSelectionBar />

            {showSkeleton ? (
                <CardSkeleton count={Math.min(count ?? 4, 6)} variant="cards" dashed={tabKey !== 'pulls'} />
            ) : reports.length === 0 ? (
                <div className="mx-auto max-w-md flex flex-col items-center text-center py-12 gap-2">
                    <div className="flex items-center justify-center h-12 w-12 rounded-full bg-fill-primary text-secondary mb-1">
                        {emptyState.icon}
                    </div>
                    <h3 className="text-base font-semibold m-0">{emptyState.title}</h3>
                    <p className="text-sm text-tertiary m-0">{emptyState.description}</p>
                </div>
            ) : (
                <>
                    {/* Each report is its own freestanding card, separated by a small gap. */}
                    <div className="flex flex-col gap-1.5">
                        {reports.map((report) => (
                            <Card
                                key={report.id}
                                report={report}
                                tabKey={tabKey}
                                onArchive={(reason, note) => archiveReport(report.id, reason, note)}
                                onRestore={() => restoreReport(report.id)}
                            />
                        ))}
                        {/* Skeleton cards continue the list while the next page loads – sleeker than a spinner. */}
                        {isLoaded && reportsResponseLoading && (
                            <CardSkeleton count={2} variant="cards" dashed={tabKey !== 'pulls'} />
                        )}
                    </div>
                    {hasMore && <div ref={sentinelRef} className="h-1" aria-hidden />}
                </>
            )}
        </div>
    )
}
