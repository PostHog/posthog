import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'

import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'
import { TodayWorkItem, workItemTitle, workItemUrl } from '~/layout/today/todayWorkItems'

function RecentLink({ item }: { item: TodayWorkItem }): JSX.Element {
    return (
        <Link
            to={workItemUrl(item)}
            subtle
            className="TodayReportLink"
            data-attr={item.kind === 'chat' ? 'today-home-recent-chat' : 'today-home-recent-session'}
        >
            {workItemTitle(item)}
        </Link>
    )
}

/** Joins links into prose: "A", "A and B", "A, B and C". */
function RecentList({ items }: { items: TodayWorkItem[] }): JSX.Element {
    return (
        <>
            {items.map((item, index) => (
                <Fragment key={`${item.kind}-${item.id}`}>
                    {index > 0 && <span>{index === items.length - 1 ? ' and ' : ', '}</span>}
                    <RecentLink item={item} />
                </Fragment>
            ))}
        </>
    )
}

/** The sessions and chats the user worked on last, written as sentences under the daily brief. */
export function TodayRecents(): JSX.Element {
    const { homeRecentItems, recentLoading, recentTasksUnavailable } = useValues(todaySpacesLogic)
    const { loadRecentTasks } = useActions(todaySpacesLogic)
    const { pickPane } = useActions(todayShellLogic)
    const [latest, ...earlier] = homeRecentItems

    const spacesButton = (
        <button type="button" data-attr="today-home-recent-spaces" onClick={() => pickPane('spaces')}>
            Spaces
        </button>
    )

    return (
        <section className="TodayHome__recents" aria-label="Recent">
            <div className="TodayHome__recentsLabel Today__label">Recent</div>
            {recentLoading && !latest ? (
                <p>Finding what you worked on last…</p>
            ) : recentTasksUnavailable && !latest ? (
                <p>
                    <span>Your recent sessions didn’t load. </span>
                    <button type="button" data-attr="today-home-recent-retry" onClick={() => loadRecentTasks()}>
                        Try again
                    </button>
                    <span>.</span>
                </p>
            ) : !latest ? (
                <p>
                    <span>Sessions and chats you open show up here. Start one from </span>
                    {spacesButton}
                    <span>.</span>
                </p>
            ) : (
                <>
                    <p>
                        <span>You were last in </span>
                        <RecentLink item={latest} />
                        {latest.timestamp && <span>{`, ${dayjs(latest.timestamp).fromNow()}`}</span>}
                        <span>.</span>
                    </p>
                    <p>
                        {earlier.length > 0 && (
                            <>
                                <span>Before that, you worked on </span>
                                <RecentList items={earlier} />
                                <span>. </span>
                            </>
                        )}
                        <span>Everything else is in </span>
                        {spacesButton}
                        <span>.</span>
                    </p>
                </>
            )}
        </section>
    )
}
