import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { ScenePin } from 'lib/components/Scenes/ScenePin'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { dayjs } from 'lib/dayjs'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneExport } from 'scenes/sceneTypes'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
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
            <ScenePanel>
                <ScenePanelInfoSection>
                    <SceneFile dataAttrKey={RESOURCE_TYPE} />
                    <SceneActivityIndicator
                        at={playlist.last_modified_at}
                        by={playlist.last_modified_by}
                        prefix="Last modified"
                    />
                </ScenePanelInfoSection>
                <ScenePanelDivider />
                <ScenePanelActionsSection>
                    <SceneDuplicate dataAttrKey={RESOURCE_TYPE} onClick={() => duplicatePlaylist()} />
                    <ScenePin
                        dataAttrKey={RESOURCE_TYPE}
                        onClick={() => updatePlaylist({ pinned: !playlist.pinned })}
                        isPinned={playlist.pinned ?? false}
                    />
                    <SceneMetalyticsSummaryButton dataAttrKey={RESOURCE_TYPE} />
                </ScenePanelActionsSection>
                <ScenePanelDivider />
                <ScenePanelActionsSection>
                    <ButtonPrimitive variant="danger" onClick={() => deletePlaylist()} menuItem>
                        Delete collection
                    </ButtonPrimitive>
                </ScenePanelActionsSection>
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
                    actions={
                        <LemonButton
                            type="primary"
                            disabledReason={showFilters && !hasChanges ? 'No changes to save' : undefined}
                            loading={hasChanges && playlistLoading}
                            onClick={() => {
                                showFilters ? updatePlaylist() : setShowFilters(!showFilters)
                            }}
                            size="small"
                        >
                            {showFilters ? <>Save changes</> : <>Edit</>}
                        </LemonButton>
                    }
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
