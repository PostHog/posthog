import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { libraryObjectHref, libraryObjectName, libraryTypeLabel } from 'scenes/library/libraryUtils'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import { todayLogic } from './todayLogic'
import { TodaySectionTitle } from './TodaySectionTitle'

function RecentObjectRow({ entry }: { entry: FileSystemEntry }): JSX.Element {
    const typeLabel = libraryTypeLabel(entry.type)
    return (
        <li className="TodayRecentRow">
            <span className="TodayRecentIcon" aria-hidden>
                {iconForType(entry.type as FileSystemIconType | undefined)}
            </span>
            <LinkPrimitive
                to={libraryObjectHref(entry) ?? undefined}
                className="TodayInlineLink truncate"
                data-attr="today-home-recent-object"
            >
                {libraryObjectName(entry)}
            </LinkPrimitive>
            <span className="TodayRecentRow__meta">
                {typeLabel && <span>{typeLabel}</span>}
                {typeLabel && entry.last_viewed_at && <span className="TodayRecentRow__time"> · </span>}
                {entry.last_viewed_at && (
                    <time className="TodayRecentRow__time" dateTime={entry.last_viewed_at}>
                        {dayjs(entry.last_viewed_at).fromNow()}
                    </time>
                )}
            </span>
        </li>
    )
}

export function TodayRecents(): JSX.Element {
    const { recentObjects, recentsHasLoaded } = useValues(todayLogic)
    const { pickPane } = useActions(todayShellLogic)
    const titleId = useId()

    const productsButton = (
        <button
            type="button"
            className="TodayInlineAction"
            data-attr="today-home-recent-library"
            onClick={() => pickPane('products')}
        >
            Products
        </button>
    )

    return (
        <section
            className="TodayHome__prose TodayHome__recents group/colorful-product-icons colorful-product-icons-true flex flex-col gap-2.5"
            aria-labelledby={titleId}
        >
            <TodaySectionTitle id={titleId}>Recent</TodaySectionTitle>
            {!recentsHasLoaded ? (
                <p>Finding what you looked at last…</p>
            ) : recentObjects.length === 0 ? (
                <p>
                    <span>Dashboards, insights and other things you open show up here. Find them in the </span>
                    {productsButton}
                    <span>.</span>
                </p>
            ) : (
                <>
                    <ul className="TodayRecentList">
                        {recentObjects.map((entry) => (
                            <RecentObjectRow key={entry.id} entry={entry} />
                        ))}
                    </ul>
                    <p>
                        <span>Everything else is in </span>
                        {productsButton}
                        <span>.</span>
                    </p>
                </>
            )}
        </section>
    )
}
