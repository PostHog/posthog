import { IconDownload, IconEllipsis, IconNotebook, IconPin, IconPinFilled, IconTrash } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonDialog, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconComment } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useMemo } from 'react'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { PlaylistPopoverButton } from 'scenes/session-recordings/player/playlist-popover/PlaylistPopover'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { PlayerShareMenu } from 'scenes/session-recordings/player/share/PlayerShareMenu'
import { personsModalLogic } from 'scenes/trends/persons-modal/personsModalLogic'

import { NotebookNodeType } from '~/types'

import { PlayerMetaBreakpoints } from './PlayerMeta'

function PinToPlaylistButton(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { maybePersistRecording } = useActions(sessionRecordingPlayerLogic)
    const nodeLogic = useNotebookNode()

    let tooltip = logicProps.pinned ? 'Unpin from this list' : 'Pin to this list'
    let description = 'Pin'
    const { featureFlags } = useValues(featureFlagLogic)
    const isTestingSaved = featureFlags[FEATURE_FLAGS.SAVED_NOT_PINNED] === 'test'
    if (isTestingSaved) {
        tooltip = logicProps.pinned ? 'Remove from this list' : 'Save to this list (for one year)'
        description = 'Save'
    }

    return logicProps.setPinned && !logicProps.pinned ? (
        <LemonButton
            size="xsmall"
            onClick={() => {
                if (nodeLogic) {
                    // If we are in a node, then pinning should persist the recording
                    maybePersistRecording()
                }

                logicProps.setPinned?.(true)
            }}
            tooltip={tooltip}
            data-attr={logicProps.pinned ? 'unpin-from-this-list' : 'pin-to-this-list'}
            icon={<IconPin />}
        />
    ) : (
        <PlaylistPopoverButton
            tooltip={tooltip}
            setPinnedInCurrentPlaylist={logicProps.setPinned}
            icon={logicProps.pinned ? <IconPinFilled /> : <IconPin />}
            size="xsmall"
        >
            {description}
        </PlaylistPopoverButton>
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
                    {size === 'normal' && <AddToNotebookButton />}

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
                        />
                    ) : null}

                    <PinToPlaylistButton />
                </>
            ) : null}
        </div>
    )
}

const AddToNotebookButton = ({ fullWidth = false }: Pick<LemonButtonProps, 'fullWidth'>): JSX.Element => {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { setPause } = useActions(sessionRecordingPlayerLogic)

    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())

    const getCurrentPlayerTime = (): number => {
        // NOTE: We pull this value at call time as otherwise it would trigger re-renders if pulled from the hook
        const playerTime = sessionRecordingPlayerLogic.findMounted(logicProps)?.values.currentPlayerTime || 0
        return Math.floor(playerTime / 1000)
    }

    return (
        <NotebookSelectButton
            fullWidth={fullWidth}
            size="xsmall"
            icon={<IconComment />}
            resource={{
                type: NotebookNodeType.Recording,
                attrs: { id: sessionRecordingId, __init: { expanded: true } },
            }}
            onClick={() => setPause()}
            onNotebookOpened={(theNotebookLogic, theNodeLogic) => {
                const time = getCurrentPlayerTime() * 1000

                if (theNodeLogic) {
                    // Node already exists, we just add a comment
                    theNodeLogic.actions.insertReplayCommentByTimestamp(time, sessionRecordingId)
                    return
                }
                theNotebookLogic.actions.insertReplayCommentByTimestamp({
                    timestamp: time,
                    sessionRecordingId,
                })

                closeSessionPlayer()
                personsModalLogic.findMounted()?.actions.closeModal()
            }}
        >
            Comment
        </NotebookSelectButton>
    )
}

const MenuActions = ({ size }: { size: PlayerMetaBreakpoints }): JSX.Element => {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { deleteRecording, setIsFullScreen, exportRecordingToFile } = useActions(sessionRecordingPlayerLogic)

    const hasMobileExportFlag = useFeatureFlag('SESSION_REPLAY_EXPORT_MOBILE_DATA')
    const hasMobileExport = window.IMPERSONATED_SESSION || hasMobileExportFlag
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
            isStandardMode && {
                label: '.json',
                status: 'default',
                icon: <IconDownload />,
                onClick: () => exportRecordingToFile(false),
                tooltip: 'Export recording to a JSON file. This can be loaded later into PostHog for playback.',
            },
        ]
        if (size === 'small') {
            itemsArray.unshift({
                label: () => <AddToNotebookButton fullWidth={true} />,
            })
        }
        if (hasMobileExport) {
            isStandardMode &&
                itemsArray.push({
                    label: 'DEBUG - mobile.json',
                    status: 'default',
                    icon: <IconDownload />,
                    onClick: () => exportRecordingToFile(true),
                    tooltip:
                        'DEBUG - ONLY VISIBLE TO POSTHOG STAFF - Export untransformed recording to a file. This can be loaded later into PostHog for playback.',
                })
        }
        if (logicProps.playerKey !== 'modal') {
            isStandardMode &&
                itemsArray.push({
                    label: 'Delete recording',
                    status: 'danger',
                    onClick: onDelete,
                    icon: <IconTrash />,
                })
        }
        return itemsArray
    }, [logicProps.playerKey, onDelete, exportRecordingToFile, hasMobileExport, size])

    return (
        <LemonMenu items={items} buttonSize="xsmall">
            <LemonButton size="xsmall" icon={<IconEllipsis />} />
        </LemonMenu>
    )
}
