import { IconPause, IconPlay } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { colonDelimitedDuration } from 'lib/utils/durations'

import { PLAYBACK_SPEEDS } from '../../sessionPlaybackLogic'

export function SessionPlayerControls({
    playing,
    speed,
    currentMs,
    durationMs,
    onTogglePlay,
    onSetSpeed,
}: {
    playing: boolean
    speed: number
    currentMs: number
    durationMs: number
    onTogglePlay: () => void
    onSetSpeed: (speed: number) => void
}): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <LemonButton
                size="small"
                icon={playing ? <IconPause /> : <IconPlay />}
                onClick={onTogglePlay}
                aria-label={playing ? 'Pause' : 'Play'}
                data-attr="session-player-play"
            />
            <span className="text-xs text-muted font-mono">
                {colonDelimitedDuration(Math.floor(currentMs / 1000))} /{' '}
                {colonDelimitedDuration(Math.floor(durationMs / 1000))}
            </span>
            <LemonMenu
                items={PLAYBACK_SPEEDS.map((s) => ({
                    label: `${s}x`,
                    active: s === speed,
                    onClick: () => onSetSpeed(s),
                }))}
            >
                <LemonButton size="small" type="secondary" data-attr="session-player-speed">
                    {speed}x
                </LemonButton>
            </LemonMenu>
        </div>
    )
}
