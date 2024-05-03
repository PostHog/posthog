import { IconNotebook, IconPin, IconPinFilled, IconShare } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconComment } from 'lib/lemon-ui/icons'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Fragment } from 'react'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { personsModalLogic } from 'scenes/trends/persons-modal/personsModalLogic'

import { NotebookNodeType } from '~/types'

import { sessionPlayerModalLogic } from './modal/sessionPlayerModalLogic'
import { PlaylistPopoverButton } from './playlist-popover/PlaylistPopover'

function PinToPlaylistButton({
    buttonContent,
    ...buttonProps
}: {
    buttonContent: (label: string) => JSX.Element
    buttonProps?: Partial<LemonButtonProps>
}): JSX.Element {
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

    return logicProps.setPinned ? (
        <LemonButton
            {...buttonProps}
            onClick={() => {
                if (nodeLogic && !logicProps.pinned) {
                    // If we are in a node, then pinning should persist the recording
                    maybePersistRecording()
                }

                logicProps.setPinned?.(!logicProps.pinned)
            }}
            tooltip={tooltip}
            data-attr={logicProps.pinned ? 'unpin-from-this-list' : 'pin-to-this-list'}
            icon={logicProps.pinned ? <IconPinFilled /> : <IconPin />}
        />
    ) : (
        <PlaylistPopoverButton {...buttonProps}>{buttonContent(description)}</PlaylistPopoverButton>
    )
}

export function PlayerMetaLinks({ iconsOnly }: { iconsOnly: boolean }): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { setPause, setIsFullScreen } = useActions(sessionRecordingPlayerLogic)
    const nodeLogic = useNotebookNode()
    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())

    const getCurrentPlayerTime = (): number => {
        // NOTE: We pull this value at call time as otherwise it would trigger re-renders if pulled from the hook
        const playerTime = sessionRecordingPlayerLogic.findMounted(logicProps)?.values.currentPlayerTime || 0
        return Math.floor(playerTime / 1000)
    }

    const onShare = (): void => {
        setPause()
        setIsFullScreen(false)
        openPlayerShareDialog({
            seconds: getCurrentPlayerTime(),
            id: sessionRecordingId,
        })
    }

    const commonProps: Partial<LemonButtonProps> = {
        size: 'small',
    }

    const buttonContent = (label: string): JSX.Element => {
        return !iconsOnly ? <span>{label}</span> : <Fragment />
    }

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    return (
        <>
            {![SessionRecordingPlayerMode.Sharing].includes(mode) ? (
                <>
                    <NotebookSelectButton
                        {...commonProps}
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
                        {buttonContent('Comment')}
                    </NotebookSelectButton>

                    <LemonButton icon={<IconShare />} onClick={onShare} {...commonProps}>
                        {buttonContent('Share')}
                    </LemonButton>

                    {nodeLogic?.props.nodeType === NotebookNodeType.RecordingPlaylist ? (
                        <LemonButton
                            {...commonProps}
                            icon={<IconNotebook />}
                            onClick={() => {
                                nodeLogic.actions.insertAfter({
                                    type: NotebookNodeType.Recording,
                                    attrs: { id: sessionRecordingId },
                                })
                            }}
                        />
                    ) : null}

                    <PinToPlaylistButton buttonContent={buttonContent} {...commonProps} />
                </>
            ) : null}
        </>
    )
}
