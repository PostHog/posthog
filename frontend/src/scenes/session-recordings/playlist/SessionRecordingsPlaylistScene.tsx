import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { isUniversalFilters } from '../utils'
import { SessionRecordingsPlaylist } from './SessionRecordingsPlaylist'
import { convertLegacyFiltersToUniversalFilters } from './sessionRecordingsPlaylistLogic'
import { sessionRecordingsPlaylistSceneLogic } from './sessionRecordingsPlaylistSceneLogic'

export const scene: SceneExport = {
    component: SessionRecordingsPlaylistScene,
    logic: sessionRecordingsPlaylistSceneLogic,
    paramsToProps: ({ params: { id } }) => {
        return { shortId: id as string }
    },
    settingSectionId: 'environment-replay',
}

export function SessionRecordingsPlaylistScene(): JSX.Element {
    const { playlist, playlistLoading, pinnedRecordings, hasChanges } = useValues(sessionRecordingsPlaylistSceneLogic)
    const { setFilters, updatePlaylist, duplicatePlaylist, deletePlaylist, onPinnedChange } = useActions(
        sessionRecordingsPlaylistSceneLogic
    )

    const { showFilters } = useValues(playerSettingsLogic)
    const { setShowFilters } = useActions(playerSettingsLogic)

    if (playlistLoading) {
        return (
            <div className="deprecated-space-y-4 mt-6">
                <LemonSkeleton className="h-10 w-1/4" />
                <LemonSkeleton className="h-4 w-1/3" />
                <LemonSkeleton className="h-4 w-1/4" />

                <div className="flex justify-between mt-4">
                    <LemonSkeleton.Button />
                    <div className="flex gap-4">
                        <LemonSkeleton.Button />
                        <LemonSkeleton.Button />
                    </div>
                </div>

                <div className="flex justify-between gap-4 mt-8">
                    <div className="deprecated-space-y-8 w-1/4">
                        <LemonSkeleton className="h-10" repeat={10} />
                    </div>
                    <div className="flex-1" />
                </div>
            </div>
        )
    }

    if (!playlist) {
        return <NotFound object="Recording Playlist" />
    }

    return (
        // Margin bottom hacks the fact that our wrapping container has an annoyingly large padding
        <div className="-mb-14">
            <PageHeader
                buttons={
                    <div className="flex justify-between items-center gap-2">
                        <More
                            overlay={
                                <>
                                    <LemonButton
                                        onClick={() => duplicatePlaylist()}
                                        fullWidth
                                        data-attr="duplicate-playlist"
                                    >
                                        Duplicate
                                    </LemonButton>
                                    <LemonButton
                                        onClick={() =>
                                            updatePlaylist({
                                                short_id: playlist.short_id,
                                                pinned: !playlist.pinned,
                                            })
                                        }
                                        fullWidth
                                    >
                                        {playlist.pinned ? 'Unpin collection' : 'Pin collection'}
                                    </LemonButton>
                                    <LemonDivider />

                                    <LemonButton status="danger" onClick={() => deletePlaylist()} fullWidth>
                                        Delete collection
                                    </LemonButton>
                                </>
                            }
                        />

                        <LemonDivider vertical />
                        <LemonButton
                            type="primary"
                            disabledReason={showFilters && !hasChanges ? 'No changes to save' : undefined}
                            loading={hasChanges && playlistLoading}
                            onClick={() => {
                                showFilters ? updatePlaylist() : setShowFilters(!showFilters)
                            }}
                        >
                            {showFilters ? <>Save changes</> : <>Edit</>}
                        </LemonButton>
                    </div>
                }
                caption={
                    <>
                        <EditableField
                            multiline
                            name="description"
                            markdown
                            value={playlist.description || ''}
                            placeholder="Description (optional)"
                            onSave={(value) => updatePlaylist({ description: value })}
                            saveOnBlur={true}
                            maxLength={400}
                            data-attr="playlist-description"
                            compactButtons
                        />
                        <UserActivityIndicator
                            at={playlist.last_modified_at}
                            by={playlist.last_modified_by}
                            className="mt-2"
                        />
                    </>
                }
            />

            <div className="SessionRecordingPlaylistHeightWrapper">
                <SessionRecordingsPlaylist
                    logicKey={playlist.short_id}
                    // backwards compatibilty for legacy filters
                    filters={
                        playlist.filters && isUniversalFilters(playlist.filters)
                            ? playlist.filters
                            : convertLegacyFiltersToUniversalFilters({}, playlist.filters)
                    }
                    onFiltersChange={setFilters}
                    onPinnedChange={onPinnedChange}
                    pinnedRecordings={pinnedRecordings ?? []}
                    canMixFiltersAndPinned={dayjs(playlist.created_at).isBefore('2025-03-11')}
                    updateSearchParams={true}
                    type="collection"
                />
            </div>
        </div>
    )
}
