import { Button, Spinner, Text } from '@posthog/quill'

import type { ListLoadMoreFooterProps } from './ListLoadMoreFooter'
import { widerDateRange } from './playlistUtils'

export function QuillListLoadMoreFooter({
    loading,
    hasNext,
    dateFrom,
    onLoadOlder,
    onWidenDateRange,
    onShowFilters,
}: ListLoadMoreFooterProps): JSX.Element {
    const wider = widerDateRange(dateFrom)
    return (
        <div data-quill className="p-4 text-foreground">
            <div className="h-10 flex items-center justify-center gap-2 text-xs text-muted-foreground">
                {loading ? (
                    <>
                        <Spinner className="size-4" /> Loading older recordings
                    </>
                ) : hasNext ? (
                    <Button size="sm" onClick={onLoadOlder} data-attr="list-load-older">
                        Load more
                    </Button>
                ) : (
                    'No more results'
                )}
            </div>
            {!loading && !hasNext && (
                <div className="flex flex-col items-center gap-1 pt-2 pb-2">
                    <Text size="xs" variant="muted" render={<span />}>
                        Looking for older recordings?
                    </Text>
                    <div className="flex gap-2">
                        {wider && (
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => onWidenDateRange(wider.dateFrom)}
                                data-attr="list-empty-widen-date-range"
                            >
                                Search last {wider.days} days
                            </Button>
                        )}
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={onShowFilters}
                            data-attr="list-empty-expand-filters"
                        >
                            Show filters
                        </Button>
                    </div>
                </div>
            )}
        </div>
    )
}
