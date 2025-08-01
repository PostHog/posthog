import { IconPeople, IconChevronDown } from '@posthog/icons'
import { useValues } from 'kea'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { useState } from 'react'
import { urls } from 'scenes/urls'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { playerSidebarLogic } from './playerSidebarLogic'

function OtherWatchersLoading(): JSX.Element {
    return (
        <div className="flex flex-row deprecated-space-x-2 items-center justify-center px-2 py-1">
            <IconPeople />
            <LemonSkeleton.Row repeat={1} className="h-5" />
        </div>
    )
}

function OtherWatchersDisplay({ startExpanded = false }: { startExpanded?: boolean }): JSX.Element | null {
    const { viewers, viewerMembers, viewerCount } = useValues(playerSidebarLogic)
    const [isExpanded, setIsExpanded] = useState(startExpanded)

    if (viewerCount === 0) {
        return null
    }

    const varyingText = viewerCount > 1 ? 'users have' : 'user has'

    const toggleExpanded = (): void => {
        setIsExpanded(!isExpanded)
    }

    return (
        <div className="flex flex-col gap-2 px-2 py-1">
            <div className="flex flex-row deprecated-space-x-2 items-center justify-center">
                <div className="flex flex-row -space-x-1">
                    {viewers.slice(0, 3).map((viewer, index) => (
                        <div key={viewer} className="relative" style={{ zIndex: 3 - index }}>
                            <ProfilePicture user={{ email: viewer }} size="sm" />
                        </div>
                    ))}
                    {viewers.length > 3 && (
                        <div className="flex items-center justify-center w-6 h-6 bg-primary-alt rounded-full text-xs font-medium text-primary border-2 border-bg-light">
                            +{viewers.length - 3}
                        </div>
                    )}
                </div>
                <span>
                    {viewerCount} other {varyingText} watched this recording.
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
                    {viewerMembers.map((user) => (
                        <div key={user.email} className="flex items-center gap-2">
                            <Link to={urls.settings('organization', 'members')} subtle>
                                <ProfilePicture user={user} size="sm" showName={true} />
                            </Link>
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
    const { sessionPlayerMetaDataLoading } = useValues(sessionRecordingPlayerLogic)
    const { hasOtherViewers } = useValues(playerSidebarLogic)

    return (
        <div className="rounded border bg-surface-primary">
            {sessionPlayerMetaDataLoading ? (
                <OtherWatchersLoading />
            ) : hasOtherViewers ? (
                <OtherWatchersDisplay startExpanded={startExpanded} />
            ) : (
                <NoOtherWatchers />
            )}
        </div>
    )
}
