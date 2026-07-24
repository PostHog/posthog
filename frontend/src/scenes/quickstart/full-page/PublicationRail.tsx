import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { Link } from 'lib/lemon-ui/Link'

import { PublicationFeedKey, QuickstartPublication } from '../publications'
import { captureQuickstartAction } from '../shared/captureQuickstartAction'
import { LoadMoreSentinel } from './LoadMoreSentinel'
import { PublicationCard } from './PublicationCard'
import { PublicationSkeletonCard } from './PublicationSkeletonCard'

export function PublicationRail({
    feed,
    title,
    viewAllUrl,
    viewAllLabel,
    endLabel,
    publications,
    loading,
    hasMore,
    onLoadMore,
}: {
    feed: PublicationFeedKey
    title: string
    viewAllUrl: string
    viewAllLabel: string
    endLabel: string
    publications: QuickstartPublication[]
    loading: boolean
    hasMore: boolean
    onLoadMore: () => void
}): JSX.Element | null {
    if (!loading && publications.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold mb-0">{title}</h3>
                <Link
                    to={viewAllUrl}
                    target="_blank"
                    className="text-sm"
                    onClick={() => captureQuickstartAction(`view_all_${feed}`)}
                    data-attr={`quickstart-publications-view-all-${feed}`}
                >
                    {viewAllLabel}
                </Link>
            </div>
            <ScrollableShadows
                direction="horizontal"
                innerClassName="snap-x"
                contentClassName="flex w-max min-w-full items-stretch gap-4 pb-1"
                styledScrollbars
            >
                {publications.map((publication) => (
                    <div key={publication.url} className="w-72 shrink-0 snap-start">
                        <PublicationCard publication={publication} feed={feed} />
                    </div>
                ))}
                {loading &&
                    Array.from({ length: publications.length === 0 ? 4 : 2 }, (_, index) => (
                        <div key={`skeleton-${index}`} className="w-72 shrink-0">
                            <PublicationSkeletonCard />
                        </div>
                    ))}
                {!loading && hasMore && <LoadMoreSentinel onVisible={onLoadMore} />}
                {!loading && !hasMore && publications.length > 0 && (
                    <div className="w-56 shrink-0 snap-start flex items-center justify-center rounded border border-dashed p-4 text-center">
                        <Link
                            to={viewAllUrl}
                            target="_blank"
                            className="text-sm"
                            onClick={() => captureQuickstartAction(`view_all_${feed}`)}
                            data-attr={`quickstart-publications-feed-end-${feed}`}
                        >
                            {endLabel}
                        </Link>
                    </div>
                )}
            </ScrollableShadows>
        </div>
    )
}
