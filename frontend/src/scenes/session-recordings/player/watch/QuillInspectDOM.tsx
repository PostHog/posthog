import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export function QuillInspectDOM({ filled = false }: { filled?: boolean }): JSX.Element {
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const { openExplorer } = useActions(sessionRecordingPlayerLogic)

    return (
        <Button
            size={filled ? 'default' : 'sm'}
            variant={filled ? 'secondary' : 'default'}
            onClick={openExplorer}
            tooltip="Inspect the DOM as it was at this moment in the session. Analyze the structure and elements captured during the recording."
            disabledReason={
                sessionPlayerMetaData?.snapshot_source === 'mobile' ? 'Only available for web recordings' : undefined
            }
            data-attr="explore-dom"
        >
            <IconSearch />
            Inspect DOM
        </Button>
    )
}
