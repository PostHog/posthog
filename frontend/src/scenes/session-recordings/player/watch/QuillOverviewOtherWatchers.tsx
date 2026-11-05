import { useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconPeople } from '@posthog/icons'
import { AvatarGroup, Button, Skeleton } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { userLogic } from 'scenes/userLogic'

import { QuillUserAvatar } from './QuillUserAvatar'

const MAX_BUBBLES = 6

export function QuillOverviewOtherWatchers(): JSX.Element {
    const { sessionPlayerMetaDataLoading, sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const { user: currentUser } = useValues(userLogic)
    const [expanded, setExpanded] = useState(false)

    const otherViewers = (sessionPlayerMetaData?.viewers ?? []).filter((viewer) => viewer !== currentUser?.email)
    const count = otherViewers.length

    return (
        <div className="rounded border border-border bg-card">
            {sessionPlayerMetaDataLoading ? (
                <div className="flex items-center justify-center gap-2 px-2 py-1">
                    <IconPeople />
                    <Skeleton className="h-5 w-48" />
                </div>
            ) : count === 0 ? (
                <div className="flex items-center justify-center gap-2 px-2 py-1">
                    <IconPeople />
                    <span>Nobody else has watched this recording.</span>
                </div>
            ) : (
                <div className="flex flex-col gap-2 px-2 py-1">
                    <div className="flex items-center justify-center gap-2 ph-no-capture">
                        <AvatarGroup stacked size="xs">
                            {otherViewers.slice(0, MAX_BUBBLES).map((email) => (
                                <QuillUserAvatar key={email} user={{ email }} size="xs" />
                            ))}
                        </AvatarGroup>
                        <span>
                            {count} other {count > 1 ? 'users have' : 'user has'} watched this recording.
                        </span>
                        <Button
                            size="icon-xs"
                            className="ml-2"
                            aria-expanded={expanded}
                            aria-label={expanded ? 'Hide watchers' : 'Show watchers'}
                            onClick={() => setExpanded(!expanded)}
                            data-attr="player-overview-watchers-toggle"
                        >
                            <IconChevronDown className={cn('transition-transform', expanded && 'rotate-180')} />
                        </Button>
                    </div>
                    {expanded && (
                        <div className="flex flex-col gap-1 mt-2 border-t border-border pt-2">
                            {otherViewers.map((email) => (
                                <div key={email} className="flex items-center gap-2 text-sm ph-no-capture">
                                    <QuillUserAvatar user={{ email }} size="xs" />
                                    <span className="truncate">{email === currentUser?.email ? 'you' : email}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
