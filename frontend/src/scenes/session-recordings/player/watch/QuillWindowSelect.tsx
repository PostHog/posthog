import { useActions, useValues } from 'kea'

import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

// The select has no empty value, so "follow the user" takes a string of its own.
const FOLLOW_USER = 'follow'

export function QuillWindowSelect({ filled = false }: { filled?: boolean }): JSX.Element | null {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { windowIds, trackedWindow, currentWindowIndex, loading } = useValues(playerMetaLogic(logicProps))
    const { setTrackedWindow } = useActions(playerMetaLogic(logicProps))
    const floatingContainer = useFloatingContainer()

    if (loading || windowIds.length <= 1) {
        return null
    }

    const windowOptions = [
        { value: FOLLOW_USER, label: <IconWindow value={currentWindowIndex} className="text-muted-foreground" /> },
        ...windowIds.map((windowId) => ({
            value: String(windowId),
            label: <IconWindow value={windowId} className="text-muted-foreground" />,
        })),
    ]

    return (
        <Select
            items={windowOptions}
            value={trackedWindow === null ? FOLLOW_USER : String(trackedWindow)}
            onValueChange={(value: string | null) =>
                setTrackedWindow(value === null || value === FOLLOW_USER ? null : Number(value))
            }
        >
            <SelectTrigger
                render={<Button variant={filled ? 'secondary' : 'outline'} size={filled ? 'default' : 'sm'} />}
                className="gap-1 px-1.5"
                data-attr="player-meta-window-select"
            >
                <SelectValue />
            </SelectTrigger>
            <SelectContent container={floatingContainer}>
                <SelectItem value={FOLLOW_USER}>Follow the user</SelectItem>
                {windowIds.map((windowId) => (
                    <SelectItem key={windowId} value={String(windowId)}>
                        <span className="flex flex-row gap-x-1 items-center">
                            Follow window:&nbsp;
                            <IconWindow value={windowId} className="text-muted-foreground" />
                        </span>
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
