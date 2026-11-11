import clsx from 'clsx'

import { IconChevronRight } from '@posthog/icons'
import { LemonBadge, LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { SessionRecordingPlaylistType } from '~/types'

import { getCollectionCounts, watchNextUrl } from './collectionUtils'

type CollectionColumn = LemonTableColumn<SessionRecordingPlaylistType, keyof SessionRecordingPlaylistType | undefined>

export const COLUMN_WIDTHS = {
    leading: 48,
    count: 72,
    watchNext: 140,
    createdBy: 160,
    lastModified: 140,
    actions: 48,
}

export function nameColumn(): CollectionColumn {
    return {
        title: 'Name',
        dataIndex: 'name',
        render: function Render(name, { short_id, derived_name, description, is_synthetic }) {
            return (
                <>
                    <Link
                        className={clsx('font-semibold', !name && 'italic')}
                        to={urls.replayPlaylist(short_id)}
                        data-attr={
                            is_synthetic
                                ? 'collections-scene-table-clicked-synthetic-collection'
                                : 'collections-scene-table-clicked-user-collection'
                        }
                    >
                        {(name as string) || derived_name || 'Unnamed'}
                    </Link>
                    {description ? <div className="truncate">{description}</div> : null}
                </>
            )
        },
    }
}

export function countColumn(): CollectionColumn {
    return {
        dataIndex: 'recordings_counts',
        title: 'Count',
        tooltip: 'Count of recordings in the collection',
        width: COLUMN_WIDTHS.count,
        render: function Render(recordings_counts) {
            const counts = getCollectionCounts(recordings_counts)
            const tooltip = (
                <div className="text-start">
                    {counts ? (
                        counts.total && counts.total > 0 ? (
                            counts.unwatched > 0 ? (
                                <p>
                                    You have {counts.unwatched} unwatched recordings to watch out of a total of{' '}
                                    {counts.total} in this collection.
                                </p>
                            ) : (
                                <p>You have watched all of the {counts.total} recordings in this collection.</p>
                            )
                        ) : (
                            <p>No results found for this collection.</p>
                        )
                    ) : (
                        <p>Counts have not yet been calculated for this collection.</p>
                    )}
                </div>
            )

            return (
                <div className="flex items-center justify-start w-full h-full">
                    <Tooltip title={tooltip}>
                        {counts ? (
                            <span className="flex items-center cursor-help">
                                <LemonBadge.Number
                                    status={counts.unwatched ? 'primary' : 'muted'}
                                    className="text-xs cursor-pointer"
                                    count={counts.total || 0}
                                    maxDigits={3}
                                    showZero={true}
                                />
                            </span>
                        ) : (
                            <span>
                                <LemonBadge status="muted" content="?" className="cursor-pointer" />
                            </span>
                        )}
                    </Tooltip>
                </div>
            )
        },
    }
}

export function watchNextColumn(): CollectionColumn {
    return {
        width: COLUMN_WIDTHS.watchNext,
        align: 'right',
        render: function Render(_, playlist) {
            const counts = getCollectionCounts(playlist.recordings_counts)
            return counts && counts.unwatched > 0 ? (
                <LemonButton
                    size="small"
                    type="secondary"
                    to={watchNextUrl(playlist.short_id)}
                    data-attr="collections-scene-watch-next"
                    className="whitespace-nowrap"
                    sideIcon={<IconChevronRight />}
                >
                    Watch next
                </LemonButton>
            ) : null
        },
    }
}
