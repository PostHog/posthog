import { useActions, useValues } from 'kea'

import { IconRabbit, IconTortoise } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { humanFriendlyDuration } from 'lib/utils/durations'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { QuillMenuItems } from 'scenes/session-recordings/playlist/QuillMenuItems'

export function QuillSetPlaybackSpeed({ filled = false }: { filled?: boolean }): JSX.Element {
    const { speed, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { setSpeed } = useActions(sessionRecordingPlayerLogic)
    const Icon = speed === 0.5 ? IconTortoise : IconRabbit

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size={filled ? 'default' : 'sm'}
                        variant={filled || speed !== 1 ? 'secondary' : 'default'}
                        data-attr="session-recording-speed-select"
                    />
                }
            >
                <Icon className="text-lg" style={{ stroke: 'currentColor', strokeWidth: '0.5' }} />
                Speed {speed}x
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <QuillMenuItems
                    items={PLAYBACK_SPEEDS.map((speedToggle) => ({
                        label: (
                            <span className="flex w-full justify-between gap-2">
                                <span>{speedToggle}x</span>
                                <span className="text-muted-foreground">
                                    ({humanFriendlyDuration(sessionPlayerData.durationMs / speedToggle / 1000)})
                                </span>
                            </span>
                        ),
                        onClick: () => setSpeed(speedToggle),
                        active: speed === speedToggle,
                        'data-attr': `speed-${speedToggle}x`,
                    }))}
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
