import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import {
    IconCheck,
    IconDownload,
    IconEllipsis,
    IconMinusSmall,
    IconNotebook,
    IconPlusSmall,
    IconTrash,
} from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonDialog, LemonMenu, LemonMenuItems, LemonTag } from '@posthog/lemon-ui'

import { AccessControlAction, getAccessControlDisabledReason } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconBlank } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { PlaylistPopoverButton } from 'scenes/session-recordings/player/playlist-popover/PlaylistPopover'
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { PlayerShareMenu } from 'scenes/session-recordings/player/share/PlayerShareMenu'
import { personsModalLogic } from 'scenes/trends/persons-modal/personsModalLogic'

import { AccessControlResourceType } from '~/types'
import { AccessControlLevel } from '~/types'

import { PlayerMetaBreakpoints } from './PlayerMeta'

function PinToPlaylistButton(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { maybePersistRecording } = useActions(sessionRecordingPlayerLogic)
    const nodeLogic = useNotebookNode()

    const tooltip = logicProps.pinned ? 'Remove from collection' : 'Add to collection'
    const description = logicProps.pinned ? 'Remove from collection' : 'Add to collection'

    return logicProps.setPinned && !logicProps.pinned ? (
        <LemonButton
            size="xsmall"
            onClick={() => {
                if (nodeLogic) {
                    // If we are in a node, then pinning should persist that recording
                    maybePersistRecording()
                }

                logicProps.setPinned?.(true)
            }}
            tooltip={tooltip}
            data-attr={logicProps.pinned ? 'unpin-from-this-list' : 'pin-to-this-list'}
            icon={<IconPlusSmall />}
        />
    ) : (
        <AccessControlAction
            resourceType={AccessControlResourceType.SessionRecording}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <PlaylistPopoverButton
                tooltip={tooltip}
                setPinnedInCurrentPlaylist={logicProps.setPinned}
                icon={logicProps.pinned ? <IconMinusSmall /> : <IconPlusSmall />}
                size="xsmall"
            >
                {description}
            </PlaylistPopoverButton>
        </AccessControlAction>
    )
}

export function PlayerMetaLinks({ size }: { size: PlayerMetaBreakpoints }): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const nodeLogic = useNotebookNode()

    return (
        <div className="flex">
            {![SessionRecordingPlayerMode.Sharing].includes(mode) ? (
                <>
                    {sessionRecordingId && (
                        <div className="flex items-center gap-0.5">
                            <MenuActions size={size} />
                        </div>
                    )}

                    <PlayerShareMenu />

                    {size === 'normal' && nodeLogic?.props.nodeType === NotebookNodeType.RecordingPlaylist ? (
                        <LemonButton
                            size="xsmall"
                            icon={<IconNotebook />}
                            onClick={() => {
                                nodeLogic.actions.insertAfter({
                                    type: NotebookNodeType.Recording,
                                    attrs: { id: sessionRecordingId },
                                })
                            }}
                            tooltip="Comment in a notebook"
                            data-attr="player-meta-add-replay-to-notebook"
                        />
                    ) : null}

                    <PinToPlaylistButton />
                </>
            ) : null}
        </div>
    )
}

const AddToNotebookButton = ({ fullWidth = false }: Pick<LemonButtonProps, 'fullWidth'>): JSX.Element => {
    const { sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const { setPause } = useActions(sessionRecordingPlayerLogic)

    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())

    return (
        <NotebookSelectButton
            fullWidth={fullWidth}
            size="xsmall"
            icon={<IconNotebook />}
            resource={{
                type: NotebookNodeType.Recording,
                attrs: { id: sessionRecordingId, __init: { expanded: true } },
            }}
            onClick={() => setPause()}
            onNotebookOpened={() => {
                closeSessionPlayer()
                personsModalLogic.findMounted()?.actions.closeModal()
            }}
        >
            Add to notebook
        </NotebookSelectButton>
    )
}

const MenuActions = ({ size }: { size: PlayerMetaBreakpoints }): JSX.Element => {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { deleteRecording, setIsFullScreen, exportRecordingToFile, exportRecordingToVideoFile } =
        useActions(sessionRecordingPlayerLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { skipInactivitySetting } = useValues(playerSettingsLogic)
    const { setSkipInactivitySetting } = useActions(playerSettingsLogic)

    const isStandardMode =
        (logicProps.mode ?? SessionRecordingPlayerMode.Standard) === SessionRecordingPlayerMode.Standard

    const onDelete = useMemo(
        () => () => {
            setIsFullScreen(false)
            LemonDialog.open({
                title: 'Delete recording',
                description: 'Are you sure you want to delete this recording? This cannot be undone.',
                secondaryButton: {
                    children: 'Cancel',
                },
                primaryButton: {
                    children: 'Delete',
                    status: 'danger',
                    onClick: deleteRecording,
                },
            })
        },
        [deleteRecording, setIsFullScreen]
    )

    const items: LemonMenuItems = useMemo(() => {
        const itemsArray: LemonMenuItems = [
            {
                label: () => <AddToNotebookButton fullWidth={true} />,
            },
            {
                label: 'Skip inactivity',
                'data-attr': 'skip-inactivity-menu-item',
                title: 'Skip inactive parts of the recording',
                onClick: () => {
                    return setSkipInactivitySetting(!skipInactivitySetting)
                },
                status: skipInactivitySetting ? 'danger' : 'default',
                icon: skipInactivitySetting ? <IconCheck /> : <IconBlank />,
            },
            isStandardMode && {
                label: 'PostHog .json',
                status: 'default',
                icon: <IconDownload />,
                onClick: () => exportRecordingToFile(),
                tooltip:
                    'Export PostHog recording data to a JSON file. This can be loaded later into PostHog for playback.',
                'data-attr': 'replay-export-posthog-json',
            },
            isStandardMode && featureFlags[FEATURE_FLAGS.REPLAY_EXPORT_FULL_VIDEO]
                ? {
                      label: (
                          <div className="flex w-full gap-x-2 justify-between items-center">
                              Export to MP4{' '}
                              <LemonTag type="warning" size="small">
                                  BETA
                              </LemonTag>
                          </div>
                      ),
                      status: 'default',
                      icon: <IconDownload />,
                      onClick: () => exportRecordingToVideoFile(),
                      tooltip: 'Export PostHog recording data to MP4 video file.',
                      'data-attr': 'replay-export-mp4',
                  }
                : null,
        ]

        if (logicProps.playerKey !== 'modal') {
            isStandardMode &&
                itemsArray.push({
                    label: 'Delete recording',
                    status: 'danger',
                    onClick: onDelete,
                    icon: <IconTrash />,
                    disabledReason: getAccessControlDisabledReason(
                        AccessControlResourceType.SessionRecording,
                        AccessControlLevel.Editor
                    ),
                    tooltip: 'Delete recording',
                    'data-attr': 'replay-delete-recording',
                })
        }
        return itemsArray
        // oxlint-disable-next-line exhaustive-deps
    }, [logicProps.playerKey, onDelete, exportRecordingToFile, size, skipInactivitySetting])

    return (
        <LemonMenu items={items} buttonSize="xsmall">
            <LemonButton size="xsmall" icon={<IconEllipsis />} />
        </LemonMenu>
    )
}
