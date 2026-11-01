import { LemonTable } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { SessionRecordingPlaylistType } from '~/types'

import { BUILT_IN_COLLECTION_ICONS } from './builtInCollectionIcons'
import { COLUMN_WIDTHS, countColumn, nameColumn, watchNextColumn } from './collectionColumns'
import { CollectionSectionHeading } from './CollectionSectionHeading'

const columns: LemonTableColumns<SessionRecordingPlaylistType> = [
    {
        width: COLUMN_WIDTHS.leading,
        render: function Render(_, { short_id }) {
            return (
                <span className="flex items-center justify-center w-9 h-8 text-xl text-secondary">
                    {BUILT_IN_COLLECTION_ICONS[short_id]}
                </span>
            )
        },
    },
    countColumn(),
    nameColumn(),
    { width: COLUMN_WIDTHS.createdBy + COLUMN_WIDTHS.lastModified, render: () => null },
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
