import './LiveUserCount.scss'

import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPerson, IconVideoCamera } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { humanFriendlyLargeNumber, humanFriendlyNumber, pluralize } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { LiveUserCountLogicProps, liveUserCountLogic } from './liveUserCountLogic'

interface LiveUserCountTooltipContentProps {
    pollIntervalMs?: number
    showUpdatedTimeInTooltip?: boolean
}

function LiveUserCountTooltipContent({
    pollIntervalMs,
    showUpdatedTimeInTooltip,
}: LiveUserCountTooltipContentProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const logicProps: LiveUserCountLogicProps = { pollIntervalMs }
    const { statsUpdatedSecondsAgo, liveUserCount } = useValues(liveUserCountLogic(logicProps))
    const { setIsHovering } = useActions(liveUserCountLogic(logicProps))

    useEffect(() => {
        setIsHovering(true)
        return () => setIsHovering(false)
    }, [setIsHovering])

    if (liveUserCount == null) {
        return null
    }

    const usersOnlineString = `${humanFriendlyNumber(liveUserCount)} ${
        liveUserCount === 1 ? 'user has' : 'users have'
    } been seen recently`
    const inTeamString = currentTeam ? ` in ${currentTeam.name}` : ''
    const updatedString = !showUpdatedTimeInTooltip
        ? null
        : statsUpdatedSecondsAgo === 0
          ? 'updated just now'
          : statsUpdatedSecondsAgo == null
            ? ''
            : `updated ${statsUpdatedSecondsAgo} seconds ago`

    return (
        <div>
            <div>
                {usersOnlineString}
                {inTeamString}
            </div>
            {updatedString && <div>({updatedString})</div>}
        </div>
    )
}

interface LiveCountProps {
    pollIntervalMs?: number
}

export type LiveUserCountProps = {
    docLink?: string
    showUpdatedTimeInTooltip?: boolean
    dataAttr?: string
} & LiveCountProps

export function LiveUserCount({
    pollIntervalMs = 30000,
    docLink,
    showUpdatedTimeInTooltip = true,
}: LiveUserCountProps): JSX.Element | null {
    const { liveUserCount } = useValues(liveUserCountLogic({ pollIntervalMs }))
    const { pauseStream, resumeStream } = useActions(liveUserCountLogic({ pollIntervalMs }))

    const isVisible = usePageVisibility()
    useEffect(() => {
        if (isVisible) {
            resumeStream()
        } else {
            pauseStream()
        }
    }, [isVisible, resumeStream, pauseStream])

    const isOnline = (liveUserCount ?? 0) > 0

    return liveUserCount === null ? null : (
        <Tooltip
            title={
                <LiveUserCountTooltipContent
                    pollIntervalMs={pollIntervalMs}
                    showUpdatedTimeInTooltip={showUpdatedTimeInTooltip}
                />
            }
            interactive={!!docLink}
            delayMs={0}
            docLink={docLink}
        >
            <div
                className={cn(
                    'flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors',
                    isOnline ? 'bg-success-highlight' : 'bg-border-light'
                )}
            >
                <div className={cn('live-user-indicator', isOnline ? 'online' : 'offline')} />
                <IconPerson className="size-4 shrink-0 min-[660px]:hidden" />
                <span className="text-xs font-medium whitespace-nowrap" data-attr="web-analytics-live-user-count">
                    <strong>{humanFriendlyLargeNumber(liveUserCount)}</strong>
                </span>
                <span className="hidden min-[660px]:inline">recently online</span>
            </div>
        </Tooltip>
    )
}

export function LiveRecordingsCount({ pollIntervalMs = 30000 }: LiveCountProps): JSX.Element | null {
    const { activeRecordings } = useValues(liveUserCountLogic({ pollIntervalMs }))
    const { pauseStream, resumeStream } = useActions(liveUserCountLogic({ pollIntervalMs }))

    const isVisible = usePageVisibility()
    useEffect(() => {
        if (isVisible) {
            resumeStream()
        } else {
            pauseStream()
        }
    }, [isVisible, resumeStream, pauseStream])

    const hasRecordings = (activeRecordings ?? 0) > 0

    if (activeRecordings === null) {
        return null
    }

    return (
        <FlaggedFeature flag={FEATURE_FLAGS.LIVE_EVENTS_ACTIVE_RECORDINGS}>
            <Tooltip
                title={
                    activeRecordings == null
                        ? 'Unable to retrieve active recordings count.'
                        : 'Session recordings currently in progress.'
                }
                placement="right"
            >
                <div
                    className={cn(
                        'flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors',
                        hasRecordings ? 'bg-success-highlight' : 'bg-border-light'
                    )}
                >
                    <div className={cn('live-user-indicator', hasRecordings ? 'online' : 'offline')} />
                    <IconVideoCamera className="size-4 shrink-0 min-[660px]:hidden" />
                    <span className="text-xs font-medium whitespace-nowrap" data-attr="live-recordings-count">
                        <strong>{humanFriendlyLargeNumber(activeRecordings)}</strong>
                    </span>
                    <span className="hidden min-[660px]:inline">
                        recently active {pluralize(activeRecordings, 'recording', undefined, false)}
                    </span>
                </div>
            </Tooltip>
        </FlaggedFeature>
    )
}
