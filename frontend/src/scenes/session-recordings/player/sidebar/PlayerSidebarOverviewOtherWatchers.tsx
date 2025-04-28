import { IconPeople } from '@posthog/icons'
import { useValues } from 'kea'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture'

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

function OtherWatchersDisplay({ metadata }: { metadata?: SessionRecordingType }): JSX.Element | null {
    if (!metadata?.viewers) {
        // to keep TS happy
        return null
    }

    const count = metadata.viewers.length
    const varyingText = count > 1 ? 'users have' : 'user has'
    return (
        <div className="flex flex-row deprecated-space-x-2 items-center justify-center px-2 py-1">
            <ProfileBubbles people={metadata.viewers.map((v) => ({ email: v }))} />
            <span>
                {count} other {varyingText} watched this recording.
            </span>
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

export function PlayerSidebarOverviewOtherWatchers(): JSX.Element {
    const { sessionPlayerMetaDataLoading, sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)

    return (
        <div className="rounded border bg-surface-primary">
            {sessionPlayerMetaDataLoading ? (
                <OtherWatchersLoading />
            ) : sessionPlayerMetaData?.viewers?.length ? (
                <OtherWatchersDisplay metadata={sessionPlayerMetaData} />
            ) : (
                <NoOtherWatchers />
            )}
        </div>
    )
}
