import { useActions, useValues } from 'kea'
import './SessionRecordingsPlaylist.scss'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { PageHeader } from 'lib/components/PageHeader'
import { sessionRecordingsPlaylistSceneLogic } from './sessionRecordingsPlaylistSceneLogic'
import { NotFound } from 'lib/components/NotFound'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { SessionRecordingsPlaylist } from './SessionRecordingsPlaylist'

export const scene: SceneExport = {
    component: SessionRecordingsPlaylistScene,
    logic: sessionRecordingsPlaylistSceneLogic,
    paramsToProps: ({ params: { id } }) => {
        return { shortId: id as string }
    },
}

export function SessionRecordingsPlaylistScene(): JSX.Element {
    const { playlist, playlistLoading, pinnedRecordings, hasChanges, derivedName } = useValues(
        sessionRecordingsPlaylistSceneLogic
    )
    const { setFilters, updatePlaylist, duplicatePlaylist, deletePlaylist, onPinnedChange } = useActions(
        sessionRecordingsPlaylistSceneLogic
    )

    const { showFilters } = useValues(playerSettingsLogic)
    const { setShowFilters } = useActions(playerSettingsLogic)

    if (!playlist && playlistLoading) {
        return (
            <div className="space-y-4 mt-6">
                <LemonSkeleton className="h-10 w-1/4" />
                <LemonSkeleton className=" w-1/3" />
                <LemonSkeleton className=" w-1/4" />

                <div className="flex justify-between mt-4">
                    <LemonSkeleton.Button />
                    <div className="flex gap-4">
                        <LemonSkeleton.Button />
                        <LemonSkeleton.Button />
                    </div>
                </div>

                <div className="flex justify-between gap-4 mt-8">
                    <div className="space-y-8 w-1/4">
                        <LemonSkeleton className="h-10" repeat={10} />
                    </div>
                    <div className="flex-1" />
                </div>
            </div>
        )
    }

    if (!playlist) {
        return <NotFound object={'Recording Playlist'} />
    }

    return (
        // Margin bottom hacks the fact that our wrapping container has an annoyingly large padding
        <div className="-mb-14">
            <PageHeader
                title={
                    <EditableField
                        name="name"
                        value={playlist.name || ''}
                        placeholder={derivedName}
                        onSave={(value) => updatePlaylist({ short_id: playlist.short_id, name: value })}
                        saveOnBlur={true}
                        maxLength={400}
                        mode={undefined}
                        data-attr="playlist-name"
                    />
                }
                buttons={
                    <div className="flex justify-between items-center gap-2">
                        <More
                            overlay={
                                <>
                                    <LemonButton
                                        status="stealth"
                                        onClick={() => duplicatePlaylist()}
                                        fullWidth
                                        data-attr="duplicate-playlist"
                                    >
                                        Duplicate
                                    </LemonButton>
                                    <LemonButton
                                        status="stealth"
                                        onClick={() =>
                                            updatePlaylist({
                                                short_id: playlist.short_id,
                                                pinned: !playlist.pinned,
                                            })
                                        }
                                        fullWidth
                                    >
                                        {playlist.pinned ? 'Unpin playlist' : 'Pin playlist'}
                                    </LemonButton>
                                    <LemonDivider />

                                    <LemonButton status="danger" onClick={() => deletePlaylist()} fullWidth>
                                        Delete playlist
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
            {playlist.short_id ? (
                <div className="SessionRecordingPlaylistHeightWrapper">
                    <SessionRecordingsPlaylist
                        filters={playlist.filters}
                        onFiltersChange={setFilters}
                        onPinnedChange={onPinnedChange}
                        pinnedRecordings={pinnedRecordings ?? []}
                    />
                </div>
            ) : null}
        </div>
    )
}
