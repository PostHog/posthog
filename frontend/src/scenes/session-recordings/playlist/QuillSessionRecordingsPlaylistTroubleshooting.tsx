import { Button, Heading, Separator } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { useListTroubleshooting } from './useListTroubleshooting'

export function QuillSessionRecordingsPlaylistTroubleshooting(): JSX.Element {
    const {
        heading,
        recordingsAreHidden,
        hiddenRecordingsCount,
        canClearFilters,
        showHiddenRecordings,
        clearFilters,
        searchLast30Days,
    } = useListTroubleshooting()

    return (
        <div data-quill className="flex flex-col gap-2 text-foreground">
            <Heading size="sm" render={<h3 />} className="m-0 text-muted-foreground">
                {heading}
            </Heading>
            <div className="flex flex-col gap-1">
                {recordingsAreHidden && (
                    <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        onClick={showHiddenRecordings}
                        data-attr="replay-empty-state-troubleshooting-show-hidden-recordings"
                    >
                        {hiddenRecordingsCount > 0
                            ? `Show ${hiddenRecordingsCount} hidden recordings`
                            : 'Show hidden recordings'}
                    </Button>
                )}
                {canClearFilters && (
                    <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        onClick={clearFilters}
                        data-attr="replay-empty-state-troubleshooting-clear-filters"
                    >
                        Clear filters
                    </Button>
                )}
                <Button
                    variant="outline"
                    size="sm"
                    className="w-full"
                    onClick={searchLast30Days}
                    data-attr="expand-replay-listing-from-default-seven-days-to-twenty-one"
                >
                    Search over the last 30 days
                </Button>
                <Separator className="my-1" />
                <Button
                    variant="link"
                    size="inline"
                    render={
                        <LinkPrimitive to="https://posthog.com/docs/session-replay/data-retention" target="_blank" />
                    }
                >
                    Recordings might be outside the retention period
                </Button>
                <Separator className="my-1" />
                <Button
                    variant="link"
                    size="inline"
                    render={
                        <LinkPrimitive
                            to="https://posthog.com/docs/session-replay/troubleshooting#4-adtracking-blockers"
                            target="_blank"
                        />
                    }
                >
                    An ad blocker might be preventing recordings
                </Button>
            </div>
        </div>
    )
}
