import './LiveUserCount.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils'
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

export interface LiveUserCountProps {
    pollIntervalMs?: number
    docLink?: string
    bordered?: boolean
    showUpdatedTimeInTooltip?: boolean
}

export function LiveUserCount({
    pollIntervalMs = 30000,
    docLink,
    bordered,
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

    return (
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
                className={clsx(
                    'flex flex-row items-center justify-center gap-x-1',
                    bordered && 'bg-surface-primary px-3 py-2 rounded border border-primary'
                )}
            >
                <div className={clsx('live-user-indicator', (liveUserCount ?? 0) > 0 ? 'online' : 'offline')} />
                <span className="whitespace-nowrap" data-attr="live-user-count">
                    {liveUserCount === null ? '–' : <strong>{humanFriendlyLargeNumber(liveUserCount)}</strong>}
                </span>
                <span>recently active recordings</span>
            </div>
        </Tooltip>
    )
}

export interface LiveRecordingsCountProps {
    pollIntervalMs?: number
    bordered?: boolean
}

export function LiveRecordingsCount({
    pollIntervalMs = 30000,
    bordered,
}: LiveRecordingsCountProps): JSX.Element | null {
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
                    className={clsx(
                        'flex justify-center items-center gap-x-1',
                        bordered && 'bg-surface-primary px-3 py-2 rounded border border-primary'
                    )}
                >
                    <div
                        className={clsx(
                            'live-user-indicator',
                            activeRecordings != null && (activeRecordings ?? 0) > 0 ? 'online' : 'offline'
                        )}
                    />
                    <span className="whitespace-nowrap" data-attr="live-recordings-count">
                        {activeRecordings === null ? (
                            '–'
                        ) : (
                            <strong>{humanFriendlyLargeNumber(activeRecordings)}</strong>
                        )}
                    </span>
                    <span>recently active recordings</span>
                </div>
            </Tooltip>
        </FlaggedFeature>
    )
}
