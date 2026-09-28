import { IconClock, IconComment, IconDownload, IconRewindPlay, IconShare, IconWarning } from '@posthog/icons'
import { LemonTable } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { SessionRecordingPlaylistType } from '~/types'

import { COLUMN_WIDTHS, countColumn, nameColumn, progressColumn, watchNextColumn } from './collectionColumns'
import { CollectionSectionHeading } from './CollectionSectionHeading'

const BUILT_IN_ICONS: Record<string, JSX.Element> = {
    'synthetic-watch-history': <IconRewindPlay />,
    'synthetic-commented': <IconComment />,
    'synthetic-shared': <IconShare />,
    'synthetic-exported': <IconDownload />,
    'synthetic-expiring': <IconClock />,
    'synthetic-frustrated': <IconWarning />,
}

const columns: LemonTableColumns<SessionRecordingPlaylistType> = [
    {
        width: COLUMN_WIDTHS.leading,
        render: function Render(_, { short_id }) {
            return (
                <span className="flex items-center justify-center w-9 h-8 text-xl text-secondary">
                    {BUILT_IN_ICONS[short_id]}
                </span>
            )
        },
    },
    countColumn(),
    nameColumn(),
    { width: COLUMN_WIDTHS.createdBy + COLUMN_WIDTHS.lastModified, render: () => null },
    progressColumn(),
    watchNextColumn(),
    { width: COLUMN_WIDTHS.actions, render: () => null },
]

export function BuiltInCollections({
    playlists,
    loading,
}: {
    playlists: SessionRecordingPlaylistType[]
    loading: boolean
}): JSX.Element {
    return (
        <div className="border rounded overflow-hidden bg-surface-primary">
            <CollectionSectionHeading title="Built-in" description="Kept up to date by PostHog." />
            <LemonTable
                embedded
                tableLayout="fixed"
                loading={loading}
                columns={columns}
                dataSource={playlists}
                rowKey="short_id"
                loadingSkeletonRows={6}
                nouns={['collection', 'collections']}
            />
        </div>
    )
}
