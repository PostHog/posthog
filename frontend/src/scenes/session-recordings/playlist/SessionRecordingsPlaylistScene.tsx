import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo } from 'react'

import { IconCopy, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { ScenePin } from 'lib/components/Scenes/ScenePin'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { SceneExport } from 'scenes/sceneTypes'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import {
    SceneMenuBar,
    SceneMenuBarCheckboxItem,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'

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
}

function PlaylistSceneLoadingSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-y-4 mt-6">
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
                <div className="flex flex-col gap-y-8 w-1/4">
                    <LemonSkeleton className="h-10" repeat={10} />
                </div>
                <div className="flex-1" />
            </div>
        </div>
    )
}

export function SessionRecordingsPlaylistScene(): JSX.Element {
    const { playlist, playlistLoading, pinnedRecordings, hasChanges } = useValues(sessionRecordingsPlaylistSceneLogic)
    const { setFilters, updatePlaylist, duplicatePlaylist, deletePlaylist, onPinnedChange } = useActions(
        sessionRecordingsPlaylistSceneLogic
    )

    const { showFilters } = useValues(playerSettingsLogic)
    const { setShowFilters } = useActions(playerSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]

    const isNewPlaylist = useMemo(() => {
        if (!playlist || playlistLoading) {
            return false
        }

        return !playlist.name
    }, [playlist, playlistLoading])

    useEffect(() => {
        if (!playlist || !playlist.name || playlistLoading) {
            return
        }

        posthog.capture('viewed playlist', {
            playlist_id: playlist.id,
            playlist_name: playlist.name,
            is_synthetic: playlist.is_synthetic,
        })
    }, [playlist, playlistLoading])

    useFileSystemLogView({
        type: 'session_recording_playlist',
        ref: playlist?.short_id,
        enabled: Boolean(playlist?.short_id && !playlistLoading && !playlist?.is_synthetic),
    })

    if (playlistLoading && !playlist) {
        return <PlaylistSceneLoadingSkeleton />
    }

    if (!playlist) {
        return <NotFound object="replay collection" />
    }

    return (
        <div>
            {sceneMenuBarEnabled && (
                <SceneMenuBar>
                    <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                        <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />
                        {!playlist.is_synthetic && (
                            <>
                                <SceneMenuBarSeparator />
                                <SceneMenuBarItem
                                    variant="destructive"
                                    onClick={() => deletePlaylist()}
                                    data-attr={`${RESOURCE_TYPE}-menubar-delete`}
                                >
                                    <IconTrash />
                                    Delete collection
                                </SceneMenuBarItem>
                            </>
                        )}
                    </SceneMenuBarMenu>
                    {!playlist.is_synthetic && (
                        <SceneMenuBarMenu label="Edit" dataAttr={`${RESOURCE_TYPE}-menubar-edit`}>
                            <SceneMenuBarItem
                                onClick={() => duplicatePlaylist()}
                                data-attr={`${RESOURCE_TYPE}-menubar-duplicate`}
                            >
                                <IconCopy />
                                Duplicate
                            </SceneMenuBarItem>
                            <SceneMenuBarSeparator />
                            <SceneMenuBarCheckboxItem
                                checked={playlist.pinned ?? false}
                                onCheckedChange={(checked) => updatePlaylist({ pinned: checked })}
                                data-attr={`${RESOURCE_TYPE}-menubar-pin`}
                            >
                                Pinned
                            </SceneMenuBarCheckboxItem>
                        </SceneMenuBarMenu>
                    )}
                </SceneMenuBar>
            )}
            <ScenePanel>
                <ScenePanelInfoSection>
                    <SceneFile dataAttrKey={RESOURCE_TYPE} />
                    <SceneActivityIndicator
                        at={playlist.last_modified_at}
                        by={playlist.last_modified_by}
                        prefix="Last modified"
                    />
                </ScenePanelInfoSection>
                {!playlist.is_synthetic && (
                    <>
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
                    </>
                )}
            </ScenePanel>

            <SceneContent className="SessionRecordingPlaylistHeightWrapper grow">
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
                    canEdit={!playlist.is_synthetic}
                    forceEdit={isNewPlaylist}
                    saveOnBlur
                    renameDebounceMs={100}
                    actions={
                        !playlist.is_synthetic ? (
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
                        ) : undefined
                    }
                />

                <SessionRecordingsPlaylist
                    logicKey={playlist.short_id}
                    // backwards compatibility for legacy filters
                    filters={
                        playlist.filters && isUniversalFilters(playlist.filters)
                            ? playlist.filters
                            : convertLegacyFiltersToUniversalFilters({}, playlist.filters)
                    }
                    onFiltersChange={setFilters}
                    onPinnedChange={onPinnedChange}
                    pinnedRecordings={pinnedRecordings ?? []}
                    updateSearchParams={true}
                    type={playlist.type === 'filters' ? 'filters' : 'collection'}
                    isSynthetic={playlist.is_synthetic}
                    description={playlist.description}
                />
            </SceneContent>
        </div>
    )
}
