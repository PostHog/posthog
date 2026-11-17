import { useActions, useValues } from 'kea'

import { IconCopy, IconPencil, IconPlus, IconPulse, IconTrash } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { metalyticsLogic } from 'lib/components/Metalytics/metalyticsLogic'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { SidePanelTab } from '~/types'

import { sessionRecordingsPlaylistSceneLogic } from './sessionRecordingsPlaylistSceneLogic'

const RESOURCE_TYPE = 'replay-collection'

export function SessionRecordingsPlaylistSceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <SessionRecordingsPlaylistSceneMenuBarInner />
}

function SessionRecordingsPlaylistSceneMenuBarInner(): JSX.Element | null {
    const { playlist, playlistLoading, hasChanges } = useValues(sessionRecordingsPlaylistSceneLogic)
    const { updatePlaylist, duplicatePlaylist, deletePlaylist, setAddRecordingsModalOpen } = useActions(
        sessionRecordingsPlaylistSceneLogic
    )
    const { showFilters } = useValues(playerSettingsLogic)
    const { setShowFilters } = useActions(playerSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { instanceId: metalyticsInstanceId } = useValues(metalyticsLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const fileActions = useSceneFileActions(RESOURCE_TYPE)

    if (!playlist) {
        return null
    }

    const saveDisabledReason = showFilters && !hasChanges ? 'No changes to save' : undefined
    const saveOrShowFilters = (): void => (showFilters ? updatePlaylist() : setShowFilters(!showFilters))

    const actions: SceneAction[] = [
        ...fileActions,
        ...(!playlist.is_synthetic
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-delete`,
                      label: 'Delete collection',
                      icon: <IconTrash />,
                      destructive: true,
                      onSelect: () => deletePlaylist(),
                  },
                  playlist.type === 'collection'
                      ? {
                            group: 'edit',
                            section: 'recordings',
                            id: `${RESOURCE_TYPE}-menubar-add-recordings`,
                            label: 'Add recordings',
                            icon: <IconPlus />,
                            opensFloatingUi: true,
                            onSelect: () => setAddRecordingsModalOpen(true),
                            pinned: { order: 1, variant: 'primary', dataAttr: 'collection-add-recordings' },
                        }
                      : {
                            group: 'edit',
                            section: 'recordings',
                            id: `${RESOURCE_TYPE}-menubar-save-or-show-filters`,
                            label: showFilters ? 'Save changes' : 'Edit',
                            keywords: ['filters'],
                            icon: <IconPencil />,
                            disabledReason: saveDisabledReason,
                            onSelect: saveOrShowFilters,
                            pinned: {
                                order: 1,
                                variant: 'primary',
                                render: () => (
                                    <Button
                                        data-attr="collection-save-or-show-filters"
                                        variant="primary"
                                        disabledReason={saveDisabledReason}
                                        loading={hasChanges && playlistLoading}
                                        onClick={saveOrShowFilters}
                                    >
                                        {showFilters ? 'Save changes' : 'Edit'}
                                    </Button>
                                ),
                            },
                        },
                  {
                      group: 'edit',
                      section: 'duplicate',
                      id: `${RESOURCE_TYPE}-menubar-duplicate`,
                      label: 'Duplicate',
                      icon: <IconCopy />,
                      onSelect: () => duplicatePlaylist(),
                  },
                  {
                      group: 'edit',
                      section: 'toggles',
                      type: 'checkbox',
                      id: `${RESOURCE_TYPE}-menubar-pin`,
                      label: 'Pinned',
                      checked: playlist.pinned ?? false,
                      onCheckedChange: (checked) => updatePlaylist({ pinned: checked }),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(!playlist.is_synthetic && metalyticsInstanceId && featureFlags[FEATURE_FLAGS.METALYTICS]
            ? ([
                  {
                      group: 'view',
                      id: `${RESOURCE_TYPE}-menubar-metalytics`,
                      label: 'View metalytics',
                      icon: <IconPulse />,
                      opensFloatingUi: true,
                      onSelect: () => openSidePanel(SidePanelTab.Activity, 'metalytics'),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(playlist.last_modified_at || playlist.last_modified_by
            ? ([
                  {
                      group: 'metadata',
                      type: 'panel',
                      id: `${RESOURCE_TYPE}-menubar-metadata`,
                      label: 'Metadata',
                      render: () => (
                          <SceneActivityIndicator
                              at={playlist.last_modified_at}
                              by={playlist.last_modified_by}
                              prefix="Last modified"
                          />
                      ),
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
