import { useActions, useValues } from 'kea'

import { IconFastForward } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { QuillInspectDOM } from './QuillInspectDOM'
import { QuillSetPlaybackSpeed } from './QuillSetPlaybackSpeed'

function IconSpeaker({ muted }: { muted: boolean }): JSX.Element {
    return (
        <svg
            width="1em"
            height="1em"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
        >
            <path d="M3 9h3.5L12 4.5v15L6.5 15H3z" />
            {muted ? <path d="m16 9 6 6m0-6-6 6" /> : <path d="M15.5 8.5a5 5 0 0 1 0 7m3-10a9.5 9.5 0 0 1 0 13" />}
        </svg>
    )
}

export function QuillPlayerBarMute(): JSX.Element {
    const { isMuted } = useValues(sessionRecordingPlayerLogic)
    const { setMuted } = useActions(sessionRecordingPlayerLogic)

    return (
        <span data-quill className="flex items-center text-foreground">
            <Button
                size="icon-sm"
                variant={isMuted ? 'secondary' : 'default'}
                aria-pressed={isMuted}
                aria-label={isMuted ? 'Unmute audio' : 'Mute audio'}
                tooltip={
                    <span className="flex items-center gap-1">
                        {isMuted ? 'Unmute audio' : 'Mute audio'} <KeyboardShortcut m />
                    </span>
                }
                onClick={() => setMuted(!isMuted)}
                data-attr="player-bar-mute"
            >
                <IconSpeaker muted={isMuted} />
            </Button>
        </span>
    )
}

export function QuillPlayerBarControls({ size }: { size: 'small' | 'normal' }): JSX.Element {
    const { skipInactivitySetting, debugMode } = useValues(playerSettingsLogic)
    const { setSkipInactivitySetting } = useActions(playerSettingsLogic)

    return (
        <div data-quill className="flex items-center gap-0.5 text-foreground" data-attr="player-bar-controls">
            {debugMode && <QuillInspectDOM iconOnly={size === 'small'} />}
            <QuillSetPlaybackSpeed short={size === 'small'} />
            <Button
                size={size === 'small' ? 'icon-sm' : 'sm'}
                variant={skipInactivitySetting ? 'secondary' : 'default'}
                aria-pressed={skipInactivitySetting}
                aria-label="Skip inactivity"
                tooltip={skipInactivitySetting ? 'Skipping inactivity. Click to play it.' : 'Skip inactivity'}
                onClick={() => setSkipInactivitySetting(!skipInactivitySetting)}
                data-attr="player-bar-skip-inactivity"
            >
                <IconFastForward />
                {size !== 'small' && 'Skip inactivity'}
            </Button>
        </div>
    )
}
