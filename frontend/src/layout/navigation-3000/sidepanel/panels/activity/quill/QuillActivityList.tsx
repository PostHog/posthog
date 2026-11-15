import { useActions, useValues } from 'kea'

import { IconList } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
    Spinner,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { sidePanelActivityLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'
import { todayContextPanelLogic } from '~/layout/today/todayContextPanelLogic'

import { QuillActivityLogRow } from './QuillActivityLogRow'

function BrowseAllButton(): JSX.Element {
    const { close } = useActions(todayContextPanelLogic)
    return (
        <Button
            variant="outline"
            onClick={close}
            render={<LinkPrimitive to={urls.advancedActivityLogs()} data-attr="browse-all-activity-logs" />}
        >
            Browse all activity logs
        </Button>
    )
}

export function QuillActivityList(): JSX.Element {
    const { allActivity, allActivityResponseLoading, allActivityHasNext, activeFilters, contextFromPage } =
        useValues(sidePanelActivityLogic)
    const { maybeLoadOlderActivity, setActiveFilters } = useActions(sidePanelActivityLogic)
    const { close } = useActions(todayContextPanelLogic)

    if (!contextFromPage?.scope) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconList />
                    </EmptyMedia>
                    <EmptyTitle>Activity follows the page you're on</EmptyTitle>
                    <EmptyDescription>
                        Open a page like dashboards, or a specific dashboard, to see its activity here.
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <BrowseAllButton />
                </EmptyContent>
            </Empty>
        )
    }

    if (allActivityResponseLoading && !allActivity.length) {
        return (
            <div className="flex flex-col gap-2">
                {Array.from({ length: 6 }, (_, index) => (
                    <Skeleton key={index} className="h-12" />
                ))}
            </div>
        )
    }

    if (!allActivity.length) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>No activity yet</EmptyTitle>
                    <EmptyDescription>
                        {activeFilters?.user
                            ? 'This member has made no changes here yet.'
                            : 'Changes made here show up in this list.'}
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent className="flex-row flex-wrap justify-center">
                    {activeFilters?.user && (
                        <Button
                            variant="outline"
                            onClick={() => setActiveFilters({ ...activeFilters, user: undefined })}
                        >
                            Clear user filter
                        </Button>
                    )}
                    <BrowseAllButton />
                </EmptyContent>
            </Empty>
        )
    }

    return (
        <div className="flex flex-col gap-1">
            {allActivity.map((logItem, index) => (
                // Keyed by the activity, so a row's expanded state never carries over to a different entry.
                <QuillActivityLogRow logItem={logItem} key={logItem.id ?? index} />
            ))}
            <div className="flex items-center justify-center py-2">
                {allActivityResponseLoading ? (
                    <Text size="xs" variant="muted" render={<span className="m-0 flex items-center gap-2" />}>
                        <Spinner />
                        Loading older activity
                    </Text>
                ) : allActivityHasNext ? (
                    <Button variant="outline" className="w-full" onClick={() => maybeLoadOlderActivity()}>
                        Load more
                    </Button>
                ) : (
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        No more results
                    </Text>
                )}
            </div>
            <Button
                variant="link-muted"
                className="self-center"
                onClick={close}
                render={<LinkPrimitive to={urls.advancedActivityLogs()} />}
            >
                Browse all activity logs
            </Button>
        </div>
    )
}
