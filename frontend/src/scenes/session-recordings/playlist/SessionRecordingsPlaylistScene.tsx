import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneCommonButtons } from 'lib/components/Scenes/SceneCommonButtons'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneExport } from 'scenes/sceneTypes'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import {
    ScenePanel,
    ScenePanelActions,
    ScenePanelCommonActions,
    ScenePanelDivider,
    ScenePanelMetaInfo,
} from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { isUniversalFilters } from '../utils'
import { SessionRecordingsPlaylist } from './SessionRecordingsPlaylist'
import { convertLegacyFiltersToUniversalFilters } from './sessionRecordingsPlaylistLogic'
import {
    SessionRecordingsPlaylistLogicProps,
    sessionRecordingsPlaylistSceneLogic,
} from './sessionRecordingsPlaylistSceneLogic'

const RESOURCE_TYPE = 'replay-collection'
export const scene: SceneExport<SessionRecordingsPlaylistLogicProps> = {
    component: SessionRecordingsPlaylistScene,
    logic: sessionRecordingsPlaylistSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ shortId: id }),
    settingSectionId: 'environment-replay',
}

export function SessionRecordingsPlaylistScene(): JSX.Element {
    const { playlist, playlistLoading, pinnedRecordings, hasChanges } = useValues(sessionRecordingsPlaylistSceneLogic)
    const { setFilters, updatePlaylist, duplicatePlaylist, deletePlaylist, onPinnedChange } = useActions(
        sessionRecordingsPlaylistSceneLogic
    )

    const { showFilters } = useValues(playerSettingsLogic)
    const { setShowFilters } = useActions(playerSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]

    const isNewPlaylist = useMemo(() => {
        if (!playlist || playlistLoading) {
            return false
        }

        return !playlist.name
    }, [playlist, playlistLoading])

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
        <div>
            <PageHeader
                buttons={
                    <div className="flex justify-between items-center gap-2">
                        {!newSceneLayout && (
                            <>
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
                            </>
                        )}

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
                    !newSceneLayout && (
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
                    )
                }
            />

            <ScenePanel>
                <ScenePanelCommonActions>
                    <SceneCommonButtons
                        dataAttrKey={RESOURCE_TYPE}
                        duplicate={{
                            onClick: () => duplicatePlaylist(),
                        }}
                        pinned={{
                            active: playlist.pinned,
                            onClick: () => updatePlaylist({ pinned: !playlist.pinned }),
                        }}
                    />
                </ScenePanelCommonActions>
                <ScenePanelMetaInfo>
                    <SceneFile dataAttrKey={RESOURCE_TYPE} />
                    <SceneActivityIndicator
                        at={playlist.last_modified_at}
                        by={playlist.last_modified_by}
                        prefix="Last modified"
                    />
                </ScenePanelMetaInfo>
                <ScenePanelDivider />
                <ScenePanelActions>
                    <SceneMetalyticsSummaryButton dataAttrKey={RESOURCE_TYPE} />
                    <ButtonPrimitive variant="danger" onClick={() => deletePlaylist()} menuItem>
                        Delete collection
                    </ButtonPrimitive>
                </ScenePanelActions>
            </ScenePanel>

            <SceneContent className="SessionRecordingPlaylistHeightWrapper">
                <SceneTitleSection
                    name={playlist.name || ''}
                    description={playlist.description || ''}
                    resourceType={{
                        type: 'session_replay',
                    }}
                    onNameChange={(name) => {
                        updatePlaylist({ name })
                    }}
                    onDescriptionChange={(description) => {
                        updatePlaylist({ description })
                    }}
                    canEdit
                    forceEdit={isNewPlaylist}
                    renameDebounceMs={1000}
                />
                <SceneDivider />

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
            </SceneContent>
        </div>
    )
}
