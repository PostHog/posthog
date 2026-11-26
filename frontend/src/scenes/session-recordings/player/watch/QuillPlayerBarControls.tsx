import { useActions, useValues } from 'kea'

import { IconFastForward } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { QuillInspectDOM } from './QuillInspectDOM'
import { PLAYER_BAR_ON_CLASS, QuillSetPlaybackSpeed } from './QuillSetPlaybackSpeed'

function IconSpeaker({ muted }: { muted: boolean }): JSX.Element {
    return (
        <svg
            // Sized to match the comment and emoji icons; quill would otherwise shrink it to 12px.
            className="size-4.5"
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
                className={cn(isMuted && PLAYER_BAR_ON_CLASS)}
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
                className={cn(skipInactivitySetting && PLAYER_BAR_ON_CLASS)}
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
