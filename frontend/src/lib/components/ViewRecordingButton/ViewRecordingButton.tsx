import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { isValidElement, ReactNode, useEffect } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonButtonProps, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { sessionSummaryProgressLogic } from 'scenes/session-recordings/player/player-meta/sessionSummaryProgressLogic'
import { UnwatchedIndicator } from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { urls } from 'scenes/urls'

import { MatchedRecording } from '~/types'

import { selectOutcome, sessionRecordingInfoLogic, SummaryOutcome } from './sessionRecordingInfoLogic'
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
    /** Opt in to fetching the AI summary outcome and surfacing it as a tooltip. Also gated on REPLAY_VIDEO_BASED_SUMMARIZATION. */
    checkSummaryOutcome?: boolean
    /** When provided, short-circuits the kea fetch (e.g. parent list already has the outcome on each row). */
    summaryOutcome?: SummaryOutcome | null
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
    checkSummaryOutcome = false,
    summaryOutcome,
    variant = ViewRecordingButtonVariant.Button,
    iconOnly = false,
    noPadding = false,
    ...props
}: ViewRecordingButtonProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const summaryFlagEnabled = !!featureFlags[FEATURE_FLAGS.REPLAY_VIDEO_BASED_SUMMARIZATION]
    const summaryOutcomeEnabled = checkSummaryOutcome && summaryFlagEnabled
    const shouldFetchSummaryOutcome = summaryOutcomeEnabled && !summaryOutcome

    const { summaryBySessionId } = useValues(sessionSummaryProgressLogic)
    const { checkRecordingInfo } = useActions(sessionRecordingInfoLogic)
    const { getRecordingExists, getSummaryOutcome } = useValues(sessionRecordingInfoLogic)

    useEffect(() => {
        if (!sessionId) {
            return
        }
        if (checkRecordingExists || shouldFetchSummaryOutcome) {
            checkRecordingInfo(sessionId, { includeOutcome: shouldFetchSummaryOutcome })
        }
    }, [checkRecordingExists, shouldFetchSummaryOutcome, sessionId, checkRecordingInfo])

    if (hasRecording === undefined && checkRecordingExists && sessionId) {
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

    // Outcome precedence: live progress beats parent-supplied prop beats persisted fetch.
    // Live is freshest mid-summarisation; the prop is a parent-list short-circuit; persisted is the kea-cached fallback.
    const liveOutcome = summaryOutcomeEnabled && sessionId ? summaryBySessionId[sessionId]?.session_outcome : null
    const persistedOutcome = shouldFetchSummaryOutcome && sessionId ? getSummaryOutcome(sessionId) : null
    const isInteractive = !disabledReason && !props.loading
    const outcomeTooltip =
        summaryOutcomeEnabled && isInteractive
            ? (selectOutcome([liveOutcome, summaryOutcome, persistedOutcome])?.description ?? undefined)
            : undefined

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
        if (outcomeTooltip) {
            return (
                <Tooltip title={outcomeTooltip}>
                    <span
                        className="inline-flex items-center"
                        data-ph-capture-attribute-view-recording-checked-existence={checkRecordingExists}
                        data-ph-capture-attribute-view-recording-has-outcome={true}
                    >
                        {linkContent}
                    </span>
                </Tooltip>
            )
        }
        return linkContent
    }

    const captureAttrs = {
        'data-ph-capture-attribute-view-recording-checked-existence': checkRecordingExists,
        'data-ph-capture-attribute-view-recording-has-outcome': !!outcomeTooltip,
    }

    if (iconOnly) {
        return (
            <LemonButton
                disabledReason={disabledReason}
                disabledReasonInteractive={isValidElement(disabledReason)}
                onClick={onClick}
                icon={sideIcon}
                tooltip={outcomeTooltip ?? 'View recording'}
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
            tooltip={outcomeTooltip}
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

export const recordingDisabledReason = (
    sessionId: string | undefined,
    recordingStatus: string | undefined,
    hasRecording?: boolean
): JSX.Element | string | null => {
    if (!sessionId && hasRecording === false) {
        return 'No recording for this event'
    } else if (!sessionId) {
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
