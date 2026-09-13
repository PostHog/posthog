import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { isValidElement, ReactNode, useEffect } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonButtonProps, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { Dayjs, dayjs } from 'lib/dayjs'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { UnwatchedIndicator } from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { urls } from 'scenes/urls'

import { MatchedRecording } from '~/types'

import { sessionRecordingInfoLogic } from './sessionRecordingInfoLogic'
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
    /** If true, automatically check if a recording exists for this session via batched API call */
    checkRecordingExists?: boolean
    /** When provided, short-circuits the kea fetch (e.g. parent list already has the outcome on each row). */
}

export type ViewRecordingButtonProps = Pick<
    LemonButtonProps,
    'size' | 'type' | 'data-attr' | 'fullWidth' | 'className' | 'loading'
> &
    ViewRecordingProps & {
        checkIfViewed?: boolean
        label?: ReactNode
        variant?: ViewRecordingButtonVariant
        iconOnly?: boolean
        noPadding?: boolean
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
    checkRecordingExists = false,
    variant = ViewRecordingButtonVariant.Button,
    iconOnly = false,
    noPadding = false,
    ...props
}: ViewRecordingButtonProps): JSX.Element {
    // $session_id arrives from untyped event properties and can be a non-string (e.g. a malformed
    // object from a broken SDK). Only a real string addresses a recording, so the raw value goes to
    // the disabled-reason check while URL and key uses are gated on this validity flag.
    const isValidSessionId = typeof sessionId === 'string' && sessionId !== ''

    const { checkRecordingInfo } = useActions(sessionRecordingInfoLogic)
    const { getRecordingExists } = useValues(sessionRecordingInfoLogic)

    useEffect(() => {
        if (!isValidSessionId) {
            return
        }
        if (checkRecordingExists) {
            checkRecordingInfo(sessionId)
        }
    }, [checkRecordingExists, isValidSessionId, sessionId, checkRecordingInfo])

    if (hasRecording === undefined && checkRecordingExists && isValidSessionId) {
        hasRecording = getRecordingExists(sessionId)
    }

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
        sessionRecordingViewedLogic({ sessionRecordingId: isValidSessionId ? sessionId : '' })
    )
    const { loadRecordingViewed } = useActions(
        sessionRecordingViewedLogic({ sessionRecordingId: isValidSessionId ? sessionId : '' })
    )

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
        const linkContent = (
            <Link
                onClick={disabledReason || props.loading ? undefined : onClick}
                disabledReason={
                    typeof disabledReason === 'string'
                        ? disabledReason
                        : disabledReason
                          ? 'Recording unavailable'
                          : null
                }
                className={clsx(
                    props.className,
                    props.loading && 'opacity-50',
                    props.fullWidth && 'w-full',
                    disabledReason && 'opacity-50'
                )}
                data-attr={props['data-attr']}
            >
                {props.loading ? <Spinner className="text-sm" /> : null}
                {label ?? 'View recording'}
                {sideIcon}
                {maybeUnwatchedIndicator}
            </Link>
        )
        return linkContent
    }

    const captureAttrs = {
        'data-ph-capture-attribute-view-recording-checked-existence': checkRecordingExists,
    }

    if (iconOnly) {
        return (
            <LemonButton
                disabledReason={disabledReason}
                disabledReasonInteractive={isValidElement(disabledReason)}
                onClick={onClick}
                icon={sideIcon}
                tooltip="View recording"
                aria-label="View recording"
                noPadding={noPadding}
                {...captureAttrs}
                {...props}
            />
        )
    }

    return (
        <LemonButton
            disabledReason={disabledReason}
            disabledReasonInteractive={isValidElement(disabledReason)}
            onClick={onClick}
            sideIcon={sideIcon}
            {...captureAttrs}
            {...props}
        >
            <div className="flex items-center gap-2 whitespace-nowrap">
                <span>{label ? label : 'View recording'}</span>
                {maybeUnwatchedIndicator}
            </div>
        </LemonButton>
    )
}

// $recording_status reports how far the recorder got at capture time, not whether a recording exists.
// Only these statuses rule a recording out. Every other one leaves the outcome open, so it warns instead.
const REPLAY_OFF_REASONS: Record<string, string> = {
    disabled: 'Session replay was turned off when this event was captured.',
    missing_config: 'The SDK could not load your replay settings, so it did not record this event.',
    rrweb_error: 'The recorder failed to start, so this event was not recorded.',
}

const UNCERTAIN_STATUS_WARNINGS: Record<string, string> = {
    buffering: 'The recorder was buffering at this time. There may not be a recording to watch.',
    lazy_loading: 'The recorder was still loading at this time. There may not be a recording to watch.',
    awaiting_config: 'The recorder was waiting for your replay settings. There may not be a recording to watch.',
    pending_config: 'The recorder was waiting for your replay settings. There may not be a recording to watch.',
    paused: 'Recording was paused at this time. There may not be a recording to watch.',
}

export const recordingDisabledReason = (
    sessionId: unknown,
    recordingStatus: string | undefined,
    hasRecording?: boolean
): JSX.Element | string | null => {
    if (sessionId != null && typeof sessionId !== 'string') {
        return 'No recording for this event'
    }
    const isValidSessionId = typeof sessionId === 'string' && sessionId !== ''
    if (!isValidSessionId && hasRecording === false) {
        return 'No recording for this event'
    } else if (!isValidSessionId) {
        return (
            <>
                No session ID associated with this event.{' '}
                <Link to="https://posthog.com/docs/data/sessions#automatically-sending-session-ids">Learn how</Link> to
                set it on all events.
            </>
        )
    } else if (hasRecording === true) {
        // We already know a recording exists, so no reported status can rule it out.
        return null
    } else if (recordingStatus && Object.hasOwn(REPLAY_OFF_REASONS, recordingStatus)) {
        return (
            <>
                {REPLAY_OFF_REASONS[recordingStatus]}{' '}
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

export const recordingWarningReason = (
    recordingDuration: number | undefined,
    minimumDuration: number | undefined,
    recordingStatus: string | undefined,
    hasRecording: boolean | undefined
): string | undefined => {
    // These warnings only caveat that a recording might not exist. Once the server has answered either
    // way, the disabled reason states the outcome, so a hedge beside it only contradicts it.
    if (hasRecording !== undefined) {
        return undefined
    }
    if (recordingDuration && minimumDuration && recordingDuration < minimumDuration) {
        const minimumDurationInSeconds = minimumDuration / 1000
        return `There is a chance this recording was not captured because the event happened earlier than the ${minimumDurationInSeconds}s minimum session duration.`
    }
    if (recordingStatus && Object.hasOwn(UNCERTAIN_STATUS_WARNINGS, recordingStatus)) {
        return UNCERTAIN_STATUS_WARNINGS[recordingStatus]
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
    const isValidSessionId = typeof sessionId === 'string' && sessionId !== ''
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const { userClickedThrough } = useActions(
        sessionRecordingViewedLogic({ sessionRecordingId: isValidSessionId ? sessionId : '' })
    )

    const onClick = (): void => {
        userClickedThrough()
        if (openPlayerIn === RecordingPlayerType.Modal) {
            const fiveSecondsBeforeEvent = timestamp ? dayjs(timestamp).valueOf() - 5000 : 0

            openSessionPlayer(
                { id: isValidSessionId ? sessionId : '', matching_events: matchingEvents ?? undefined },
                Math.max(fiveSecondsBeforeEvent, 0)
            )
        } else {
            const timestampMs = timestamp ? dayjs(timestamp).valueOf() - 5000 : undefined
            const urlParams = timestampMs ? { unixTimestampMillis: Math.max(timestampMs, 0) } : undefined
            newInternalTab(urls.replaySingle(isValidSessionId ? sessionId : '', urlParams))
        }
    }

    const disabledReason = recordingDisabledReason(sessionId, recordingStatus, hasRecording)
    const warningReason = recordingWarningReason(recordingDuration, minimumDuration, recordingStatus, hasRecording)

    return { onClick, disabledReason, warningReason }
}
