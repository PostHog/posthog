import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDownload, IconEllipsis, IconNotebook, IconTrash } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { getVideoExportDisabledReason } from 'lib/components/ExportButton/exportStatus'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { QuillMenuItems } from 'scenes/session-recordings/playlist/QuillMenuItems'
import { personsModalLogic } from 'scenes/trends/persons-modal/personsModalLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

function AddToNotebookItem(): JSX.Element {
    const { sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const { setPause } = useActions(sessionRecordingPlayerLogic)
    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())

    return (
        <span data-not-quill className="contents">
            <NotebookSelectButton
                fullWidth
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
        </span>
    )
}

export function QuillPlayerActionsMenu({ extraItems = [] }: { extraItems?: LemonMenuItems }): JSX.Element {
    const { logicProps, isMuted, hasReachedExportFullVideoLimit, sessionPlayerData } =
        useValues(sessionRecordingPlayerLogic)
    const { deleteRecording, setIsFullScreen, exportRecordingToFile, exportRecordingToVideoFile, setMuted } =
        useActions(sessionRecordingPlayerLogic)
    const { skipInactivitySetting } = useValues(playerSettingsLogic)
    const { setSkipInactivitySetting } = useActions(playerSettingsLogic)
    const [confirmDelete, setConfirmDelete] = useState(false)

    const exportAccessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Export,
        AccessControlLevel.Editor
    )
    const isStandardMode =
        (logicProps.mode ?? SessionRecordingPlayerMode.Standard) === SessionRecordingPlayerMode.Standard
    const tooLongToExportReason = getVideoExportDisabledReason(sessionPlayerData?.durationMs)
    const exportLimitReason = hasReachedExportFullVideoLimit ? 'You have reached your export limit.' : undefined

    const items: LemonMenuItems = [
        { label: () => <AddToNotebookItem /> },
        ...extraItems,
        {
            label: 'Skip inactivity',
            tooltip: 'Skip inactive parts of the recording',
            onClick: () => setSkipInactivitySetting(!skipInactivitySetting),
            active: skipInactivitySetting,
            'data-attr': 'skip-inactivity-menu-item',
        },
        {
            label: isMuted ? 'Unmute audio' : 'Mute audio',
            onClick: () => setMuted(!isMuted),
            active: false,
            'data-attr': 'mute-audio-menu-item',
        },
        isStandardMode && {
            label: 'PostHog .json',
            icon: <IconDownload />,
            onClick: () => exportRecordingToFile(),
            tooltip:
                'Export PostHog recording data to a JSON file. This can be loaded later into PostHog for playback.',
            disabledReason: exportAccessControlDisabledReason ?? undefined,
            'data-attr': 'replay-export-posthog-json',
        },
        isStandardMode && {
            label: 'Export to MP4',
            icon: <IconDownload />,
            onClick: () => exportRecordingToVideoFile(),
            tooltip: exportLimitReason ?? 'Export PostHog recording data to MP4 video file.',
            disabledReason:
                exportLimitReason ?? tooLongToExportReason ?? exportAccessControlDisabledReason ?? undefined,
            'data-attr': 'replay-export-mp4',
        },
        isStandardMode &&
            logicProps.playerKey !== 'modal' && {
                label: 'Delete recording',
                status: 'danger',
                icon: <IconTrash />,
                onClick: () => {
                    setIsFullScreen(false)
                    setConfirmDelete(true)
                },
                disabledReason: getAccessControlDisabledReason(
                    AccessControlResourceType.SessionRecording,
                    AccessControlLevel.Editor
                ),
                'data-attr': 'replay-delete-recording',
            },
    ]

    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={<Button size="icon-xs" aria-label="More actions" data-attr="player-meta-more-menu" />}
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <QuillMenuItems items={items} />
                </DropdownMenuContent>
            </DropdownMenu>
            <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Delete recording</AlertDialogTitle>
                        <AlertDialogDescription>
                            Are you sure you want to delete this recording? This cannot be undone.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <Button variant="outline" onClick={() => setConfirmDelete(false)}>
                            Cancel
                        </Button>
                        <Button
                            variant="destructive"
                            onClick={() => {
                                setConfirmDelete(false)
                                deleteRecording()
                            }}
                            data-attr="replay-delete-recording-confirm"
                        >
                            Delete
                        </Button>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    )
}
