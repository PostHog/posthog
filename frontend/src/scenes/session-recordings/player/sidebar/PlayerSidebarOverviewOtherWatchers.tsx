import { useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconPeople } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { userLogic } from 'scenes/userLogic'

import { SessionRecordingType } from '~/types'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

function OtherWatchersLoading(): JSX.Element {
    return (
        <div className="flex flex-row deprecated-space-x-2 items-center justify-center px-2 py-1">
            <IconPeople />
            <LemonSkeleton.Row repeat={1} className="h-5" />
        </div>
    )
}

function OtherWatchersDisplay({
    metadata,
    startExpanded = false,
}: {
    metadata?: SessionRecordingType
    startExpanded?: boolean
}): JSX.Element | null {
    const { user: currentUser } = useValues(userLogic)
    const [isExpanded, setIsExpanded] = useState(startExpanded)

    if (!metadata?.viewers) {
        return null
    }

    // Filter out the current user from the viewers list
    const otherViewers = metadata.viewers.filter((viewer) => viewer !== currentUser?.email)
    const count = otherViewers.length

    if (count === 0) {
        return null
    }

    const varyingText = count > 1 ? 'users have' : 'user has'

    const toggleExpanded = (): void => {
        setIsExpanded(!isExpanded)
    }

    return (
        <div className="flex flex-col gap-2 px-2 py-1">
            <div className="flex flex-row deprecated-space-x-2 items-center justify-center">
                <ProfileBubbles people={otherViewers.map((v) => ({ email: v }))} />
                <span>
                    {count} other {varyingText} watched this recording.
                </span>
                <LemonButton
                    size="small"
                    icon={<IconChevronDown className={isExpanded ? 'rotate-180' : ''} />}
                    onClick={toggleExpanded}
                    className="ml-2"
                />
            </div>

            {isExpanded && (
                <div className="flex flex-col gap-1 mt-2 border-t pt-2">
                    {otherViewers.map((viewer) => (
                        <div key={viewer} className="flex items-center gap-2">
                            <ProfilePicture user={{ email: viewer }} showName={true} size="sm" />
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

function NoOtherWatchers(): JSX.Element {
    return (
        <div className="flex flex-row deprecated-space-x-2 items-center justify-center px-2 py-1">
            <IconPeople />
            <span>Nobody else has watched this recording.</span>
        </div>
    )
}

export function PlayerSidebarOverviewOtherWatchers({
    startExpanded = false,
}: {
    startExpanded?: boolean
}): JSX.Element {
    const { sessionPlayerMetaDataLoading, sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)

    return (
        <div className="rounded border bg-surface-primary">
            {sessionPlayerMetaDataLoading ? (
                <OtherWatchersLoading />
            ) : sessionPlayerMetaData?.viewers?.length ? (
                <OtherWatchersDisplay metadata={sessionPlayerMetaData} startExpanded={startExpanded} />
            ) : (
                <NoOtherWatchers />
            )}
        </div>
    )
}
