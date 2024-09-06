import {
    IconDownload,
    IconEllipsis,
    IconMagic,
    IconNotebook,
    IconPin,
    IconPinFilled,
    IconSearch,
    IconShare,
    IconTrash,
} from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonDialog, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconComment } from 'lib/lemon-ui/icons'
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
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'

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
        <div className="flex">
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

                    {sessionRecordingId && (
                        <div className="flex items-center gap-0.5">
                            {mode === SessionRecordingPlayerMode.Standard && <MenuActions />}
                        </div>
                    )}
                </>
            ) : null}
        </div>
    )
}

const MenuActions = (): JSX.Element => {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { exportRecordingToFile, openExplorer, deleteRecording, setIsFullScreen } =
        useActions(sessionRecordingPlayerLogic)
    const { fetchSimilarRecordings } = useActions(sessionRecordingDataLogic(logicProps))

    const hasMobileExport = window.IMPERSONATED_SESSION || useFeatureFlag('SESSION_REPLAY_EXPORT_MOBILE_DATA')
    const hasSimilarRecordings = useFeatureFlag('REPLAY_SIMILAR_RECORDINGS')

    const onDelete = (): void => {
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
    }

    const items: LemonMenuItems = [
        {
            label: 'Export to file',
            onClick: () => exportRecordingToFile(false),
            icon: <IconDownload />,
            tooltip: 'Export recording to a file. This can be loaded later into PostHog for playback.',
        },
        {
            label: 'Explore DOM',
            onClick: openExplorer,
            icon: <IconSearch />,
        },
        hasMobileExport && {
            label: 'Export mobile replay to file',
            onClick: () => exportRecordingToFile(true),
            tooltip:
                'DEBUG ONLY - Export untransformed recording to a file. This can be loaded later into PostHog for playback.',
            icon: <IconDownload />,
        },
        hasSimilarRecordings && {
            label: 'Find similar recordings',
            onClick: fetchSimilarRecordings,
            icon: <IconMagic />,
            tooltip: 'DEBUG ONLY - Find similar recordings based on distance calculations via embeddings.',
        },
        logicProps.playerKey !== 'modal' && {
            label: 'Delete recording',
            status: 'danger',
            onClick: onDelete,
            icon: <IconTrash />,
        },
    ]

    return (
        <LemonMenu items={items}>
            <LemonButton size="small" icon={<IconEllipsis />} />
        </LemonMenu>
    )
}
