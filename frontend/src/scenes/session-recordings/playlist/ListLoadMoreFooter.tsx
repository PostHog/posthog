import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { widerDateRange } from './playlistUtils'

export interface ListLoadMoreFooterProps {
    loading: boolean
    hasNext: boolean
    dateFrom?: string | null
    onLoadOlder: () => void
    onWidenDateRange: (dateFrom: string) => void
    onShowFilters: () => void
}

export function ListLoadMoreFooter({
    loading,
    hasNext,
    dateFrom,
    onLoadOlder,
    onWidenDateRange,
    onShowFilters,
}: ListLoadMoreFooterProps): JSX.Element {
    const wider = widerDateRange(dateFrom)
    return (
        <div className="p-4">
            <div className="h-10 flex items-center justify-center gap-2 text-secondary">
                {loading ? (
                    <>
                        <Spinner textColored /> Loading older recordings
                    </>
                ) : hasNext ? (
                    <LemonButton data-attr="list-load-older" onClick={onLoadOlder}>
                        Load more
                    </LemonButton>
                ) : (
                    'No more results'
                )}
            </div>
            {!loading && !hasNext && (
                <div className="flex flex-col items-center gap-1 pt-2 pb-2">
                    <span className="text-xs text-secondary">Looking for older recordings?</span>
                    <div className="flex gap-2">
                        {wider && (
                            <LemonButton
                                data-attr="list-empty-widen-date-range"
                                type="secondary"
                                size="small"
                                onClick={() => onWidenDateRange(wider.dateFrom)}
                            >
                                Search last {wider.days} days
                            </LemonButton>
                        )}
                        <LemonButton
                            data-attr="list-empty-expand-filters"
                            type="secondary"
                            size="small"
                            onClick={onShowFilters}
                        >
                            Show filters
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
