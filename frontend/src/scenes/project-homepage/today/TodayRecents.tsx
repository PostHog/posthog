import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import { todayLogic } from './todayLogic'

function RecentObject({ entry }: { entry: FileSystemEntry }): JSX.Element {
    const { recentObjectPreviews } = useValues(todayLogic)
    const preview = recentObjectPreviews[entry.id]
    const link = (
        <Link to={entry.href} subtle className="TodayReportLink" data-attr="today-home-recent-object">
            {preview?.name ?? entry.path}
        </Link>
    )
    const iconAndLink = (
        <>
            <span className="TodayRecentIcon" aria-hidden>
                {iconForType(entry.type as FileSystemIconType | undefined)}
            </span>
            {preview ? (
                <TodayPreviewTrigger payload={preview} inline>
                    {link}
                </TodayPreviewTrigger>
            ) : (
                link
            )}
        </>
    )
    return preview?.typeName ? (
        <>
            <span>the </span>
            {iconAndLink}
            <span>{` ${preview.typeName}`}</span>
        </>
    ) : (
        iconAndLink
    )
}

function RecentObjectList({ entries }: { entries: FileSystemEntry[] }): JSX.Element {
    return (
        <>
            {entries.map((entry, index) => (
                <Fragment key={entry.id}>
                    {index > 0 && <span>{index === entries.length - 1 ? ' and ' : ', '}</span>}
                    <RecentObject entry={entry} />
                </Fragment>
            ))}
        </>
    )
}

export function TodayRecents(): JSX.Element {
    const { recentObjects, recentsHasLoaded } = useValues(todayLogic)
    const { pickPane } = useActions(todayShellLogic)
    const [latest, ...earlier] = recentObjects

    const libraryButton = (
        <button type="button" data-attr="today-home-recent-library" onClick={() => pickPane('products')}>
            Products
        </button>
    )

    return (
        <section
            className="TodayHome__recents group/colorful-product-icons colorful-product-icons-true"
            aria-label="Recent"
        >
            <div className="TodayHome__recentsLabel Today__label">Recent</div>
            {!recentsHasLoaded ? (
                <p>Finding what you looked at last…</p>
            ) : !latest ? (
                <p>
                    <span>Dashboards, insights and other things you open show up here. Find them in the </span>
                    {libraryButton}
                    <span>.</span>
                </p>
            ) : (
                <>
                    <p>
                        <span>You last opened </span>
                        <RecentObject entry={latest} />
                        {latest.last_viewed_at && <span>{`, ${dayjs(latest.last_viewed_at).fromNow()}`}</span>}
                        <span>.</span>
                    </p>
                    <p>
                        {earlier.length > 0 && (
                            <>
                                <span>Before that, you opened </span>
                                <RecentObjectList entries={earlier} />
                                <span>. </span>
                            </>
                        )}
                        <span>Everything else is in the </span>
                        {libraryButton}
                        <span>.</span>
                    </p>
                </>
            )}
        </section>
    )
}
