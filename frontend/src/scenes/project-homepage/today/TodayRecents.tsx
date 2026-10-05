import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { baseObjectType, libraryObjectName } from 'scenes/library/libraryUtils'

import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { fileSystemTypes } from '~/products'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { todayLogic } from './todayLogic'

/** The type's name for use mid-sentence: "feature flag", but "SQL insight" keeps its acronym. */
function typeNameInProse(entry: FileSystemEntry): string | null {
    const name = (fileSystemTypes as Record<string, { name: string }>)[baseObjectType(entry.type)]?.name
    if (!name) {
        return null
    }
    return /^[A-Z]{2}/.test(name) ? name : name.charAt(0).toLowerCase() + name.slice(1)
}

function RecentObject({ entry }: { entry: FileSystemEntry }): JSX.Element {
    const typeName = typeNameInProse(entry)
    const link = (
        <Link to={entry.href} subtle className="TodayReportLink" data-attr="today-home-recent-object">
            {libraryObjectName(entry)}
        </Link>
    )
    return typeName ? (
        <>
            <span>the </span>
            {link}
            <span>{` ${typeName}`}</span>
        </>
    ) : (
        link
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
        <button type="button" data-attr="today-home-recent-library" onClick={() => pickPane('library')}>
            Library
        </button>
    )

    return (
        <section className="TodayHome__recents" aria-label="Recent">
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
