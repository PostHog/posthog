import classNames from 'classnames'
import { useActions, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonButtonProps, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { Dayjs, dayjs } from 'lib/dayjs'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { UnwatchedIndicator } from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { urls } from 'scenes/urls'

import { MatchedRecording } from '~/types'

import { sessionRecordingViewedLogic } from './sessionRecordingViewedLogic'

export enum ViewRecordingButtonVariant {
    Button = 'button',
    Link = 'link',
}

export enum RecordingPlayerType {
    NewTab = 'new_tab',
    Modal = 'modal',
}

type ViewRecordingProps = {
    sessionId: string | undefined
    recordingStatus?: string
    recordingDuration?: number
    minimumDuration?: number
    timestamp?: string | Dayjs
    openPlayerIn?: RecordingPlayerType
    matchingEvents?: MatchedRecording[]
    hasRecording?: boolean
}

export default function ViewRecordingButton({
    sessionId,
    recordingStatus,
    recordingDuration,
    minimumDuration,
    timestamp,
    label,
    openPlayerIn = RecordingPlayerType.NewTab,
    checkIfViewed = false,
    matchingEvents,
    hasRecording,
    variant = ViewRecordingButtonVariant.Button,
    ...props
}: Pick<LemonButtonProps, 'size' | 'type' | 'data-attr' | 'fullWidth' | 'className' | 'loading'> &
    ViewRecordingProps & {
        checkIfViewed?: boolean
        label?: ReactNode
        variant?: ViewRecordingButtonVariant
    }): JSX.Element {
    const { onClick, disabledReason, warningReason } = useRecordingButton({
        sessionId,
        recordingStatus,
        recordingDuration,
        minimumDuration,
        timestamp,
        matchingEvents,
        openPlayerIn,
        hasRecording,
    })

    const { recordingViewed, recordingViewedLoading } = useValues(
        sessionRecordingViewedLogic({ sessionRecordingId: sessionId ?? '' })
    )
    const { loadRecordingViewed } = useActions(sessionRecordingViewedLogic({ sessionRecordingId: sessionId ?? '' }))

    useEffect(() => {
        if (checkIfViewed && loadRecordingViewed) {
            loadRecordingViewed()
        }
    }, [checkIfViewed, loadRecordingViewed])

    let maybeUnwatchedIndicator = null
    if (checkIfViewed) {
        if (recordingViewedLoading) {
            maybeUnwatchedIndicator = <Spinner />
        } else if (!recordingViewed?.viewed) {
            maybeUnwatchedIndicator = <UnwatchedIndicator otherViewersCount={recordingViewed?.otherViewers || 0} />
        }
    }

    const sideIcon = warningReason ? (
        <Tooltip title={warningReason}>
            <IconWarning />
        </Tooltip>
    ) : (
        <IconPlayCircle />
    )

    if (variant === ViewRecordingButtonVariant.Link) {
        return (
            <Link
                onClick={disabledReason || props.loading ? undefined : onClick}
                disabledReason={
                    typeof disabledReason === 'string'
                        ? disabledReason
                        : disabledReason
                          ? 'Recording unavailable'
                          : null
                }
                className={classNames(props.className, props.loading && 'opacity-50', props.fullWidth && 'w-full')}
                data-attr={props['data-attr']}
            >
                {props.loading ? <Spinner className="text-sm" /> : null}
                {label ?? 'View recording'}
                {sideIcon}
                {maybeUnwatchedIndicator}
            </Link>
        )
    }

    return (
        <LemonButton disabledReason={disabledReason} onClick={onClick} sideIcon={sideIcon} {...props}>
            <div className="flex items-center gap-2 whitespace-nowrap">
                <span>{label ? label : 'View recording'}</span>
                {maybeUnwatchedIndicator}
            </div>
        </LemonButton>
    )
}

export const recordingDisabledReason = (
    sessionId: string | undefined,
    recordingStatus: string | undefined,
    hasRecording?: boolean
): JSX.Element | string | null => {
    if (!sessionId) {
        return (
            <>
                No session ID associated with this event.{' '}
                <Link to="https://posthog.com/docs/data/sessions#automatically-sending-session-ids">Learn how</Link> to
                set it on all events.
            </>
        )
    } else if (recordingStatus && !['active', 'sampled', 'buffering'].includes(recordingStatus)) {
        return (
            <>
                Replay was not active when capturing this event.{' '}
                <Link to="https://posthog.com/docs/session-replay/troubleshooting#recordings-are-not-being-captured">
                    Learn why
                </Link>{' '}
                not all recordings are captured.
            </>
        )
    } else if (hasRecording === false) {
        return 'No recording for this event'
    }
    return null
}

const recordingWarningReason = (
    recordingDuration: number | undefined,
    minimumDuration: number | undefined,
    recordingStatus: string | undefined
): string | undefined => {
    if (recordingDuration && minimumDuration && recordingDuration < minimumDuration) {
        const minimumDurationInSeconds = minimumDuration / 1000
        return `There is a chance this recording was not captured because the event happened earlier than the ${minimumDurationInSeconds}s minimum session duration.`
    }
    if (recordingStatus === 'buffering') {
        return 'The recorder was buffering at this time. There may not be a recording to watch.'
    }
    return undefined
}

export function useRecordingButton({
    sessionId,
    recordingStatus,
    recordingDuration,
    minimumDuration,
    timestamp,
    matchingEvents,
    openPlayerIn,
    hasRecording,
}: ViewRecordingProps): {
    onClick: () => void
    disabledReason: JSX.Element | string | null
    warningReason: string | undefined
} {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const { userClickedThrough } = useActions(sessionRecordingViewedLogic({ sessionRecordingId: sessionId ?? '' }))

    const onClick = (): void => {
        userClickedThrough()
        if (openPlayerIn === RecordingPlayerType.Modal) {
            const fiveSecondsBeforeEvent = timestamp ? dayjs(timestamp).valueOf() - 5000 : 0

            openSessionPlayer(
                { id: sessionId ?? '', matching_events: matchingEvents ?? undefined },
                Math.max(fiveSecondsBeforeEvent, 0)
            )
        } else {
            const timestampMs = timestamp ? dayjs(timestamp).valueOf() - 5000 : undefined
            const urlParams = timestampMs ? { unixTimestampMillis: Math.max(timestampMs, 0) } : undefined
            newInternalTab(urls.replaySingle(sessionId ?? '', urlParams))
        }
    }

    const disabledReason = recordingDisabledReason(sessionId, recordingStatus, hasRecording)
    const warningReason = recordingWarningReason(recordingDuration, minimumDuration, recordingStatus)

    return { onClick, disabledReason, warningReason }
}
