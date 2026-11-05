import { useValues } from 'kea'

import { Button } from '@posthog/quill'

import { SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

export function QuillTTLWarning(): JSX.Element | null {
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const ttl = sessionPlayerMetaData?.recording_ttl
    if (!ttl || ttl > SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS) {
        return null
    }
    return (
        <div className="text-xs text-destructive">
            Expires in {ttl} days.{' '}
            <Button
                variant="link"
                size="inline"
                render={<LinkPrimitive to={urls.settings('project-replay', 'replay-retention')} />}
                data-attr="player-ttl-open-settings"
            >
                Extend retention
            </Button>
        </div>
    )
}
