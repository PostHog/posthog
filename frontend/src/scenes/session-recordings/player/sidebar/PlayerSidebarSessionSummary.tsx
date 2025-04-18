import { IconMagicWand, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonBanner, LemonRow, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
// import { FlaggedFeature } from 'lib/components/FlaggedFeature'
// import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { SessionKeyAction, SessionObjective, SessionObjectiveKeyActions } from '../player-meta/types'

function formatEventMetaInfo(event: SessionKeyAction): JSX.Element {
    return (
        <pre className="m-0 p-0 font-mono text-xs whitespace-pre">
            {`Event: ${event.event}
            Event type: ${event.event_type}
            Error: ${event.error ? 'Yes' : 'No'}
            Timestamp: ${event.timestamp}
            Milliseconds since start: ${event.milliseconds_since_start}
            Window ID: ${event.window_id}
            Current URL: ${event.current_url}`}
        </pre>
    )
}

function formatMsIntoTime(ms: number): string {
    const seconds = Math.floor(ms / 1000)
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    const remainingSeconds = seconds % 60

    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${remainingSeconds
        .toString()
        .padStart(2, '0')}`
}

const isValidTimestamp = (ms: unknown): ms is number => typeof ms === 'number' && !isNaN(ms) && ms >= 0

interface SessionObjectiveViewProps {
    objective: SessionObjective
    keyActions: SessionObjectiveKeyActions[]
    onSeekToTime: (time: number) => void
}

function SessionObjectiveView({ objective, keyActions, onSeekToTime }: SessionObjectiveViewProps): JSX.Element {
    return (
        <div key={objective.name} className="mb-4">
            <LemonRow fullWidth className="dashboard-row" outlined>
                <h3 className="mb-0">{objective.name}</h3>
                <br />
                <p>{objective.summary}</p>
                <p>Success: {objective.success ? 'Yes' : 'No'}</p>
            </LemonRow>

            {keyActions?.map((keyAction) =>
                keyAction.events?.map((event: SessionKeyAction, eventIndex: number) =>
                    isValidTimestamp(event.milliseconds_since_start) ? (
                        <div
                            key={`${objective.name}-${eventIndex}`}
                            className={`border-b cursor-pointer py-2 px-2 hover:bg-primary-alt-highlight ${
                                event.error ? 'bg-danger-highlight' : ''
                            }`}
                            onClick={() => {
                                if (!isValidTimestamp(event.milliseconds_since_start)) {
                                    return
                                }
                                onSeekToTime(event.milliseconds_since_start)
                            }}
                        >
                            <div className="flex flex-row gap-2">
                                <span className="text-muted-alt shrink-0 min-w-[4rem] font-mono text-xs">
                                    {formatMsIntoTime(event.milliseconds_since_start)}
                                    <div className="flex flex-row gap-2 mt-1">
                                        {event.current_url ? (
                                            <Link to={event.current_url} target="_blank">
                                                <Tooltip title={event.current_url} placement="top">
                                                    <span className="font-mono text-xs text-muted-alt">url</span>
                                                </Tooltip>
                                            </Link>
                                        ) : null}
                                        <Tooltip title={formatEventMetaInfo(event)} placement="top">
                                            <span className="font-mono text-xs text-muted-alt">meta</span>
                                        </Tooltip>
                                    </div>
                                </span>

                                <span className="text-xs break-words">{event.description}</span>
                            </div>
                        </div>
                    ) : null
                )
            )}
        </div>
    )
}

function SessionSummary(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)
    const { sessionSummary, summaryHasHadFeedback } = useValues(playerMetaLogic(logicProps))
    const { sessionSummaryFeedback } = useActions(playerMetaLogic(logicProps))

    return (
        <div className="flex flex-col">
            {sessionSummary ? (
                <>
                    <>
                        {sessionSummary.session_outcome ? (
                            <LemonBanner className="mb-3" type="info" action={undefined} onClose={undefined}>
                                <div className="text-sm break-words py-1 px-1 font-normal">
                                    <b>Session outcome:</b> {sessionSummary.session_outcome.description}
                                    <br />
                                    Success: {sessionSummary.session_outcome.success ? 'Yes' : 'No'}
                                </div>
                            </LemonBanner>
                        ) : null}
                    </>

                    <div>
                        <h2>Objectives:</h2>
                        {sessionSummary?.objectives?.map((objective) => {
                            const matchingKeyActions = sessionSummary?.key_actions?.filter(
                                (keyAction) => keyAction.objective === objective.name
                            )
                            return (
                                <SessionObjectiveView
                                    key={objective.name}
                                    objective={objective}
                                    keyActions={matchingKeyActions || []}
                                    onSeekToTime={seekToTime}
                                />
                            )
                        })}
                    </div>

                    <div className="text-right mb-2 mt-4">
                        <p>Is this a good summary?</p>
                        <div className="flex flex-row gap-2 justify-end">
                            <LemonButton
                                size="xsmall"
                                type="primary"
                                icon={<IconThumbsUp />}
                                disabledReason={summaryHasHadFeedback ? 'Thanks for your feedback!' : undefined}
                                onClick={() => {
                                    sessionSummaryFeedback('good')
                                }}
                            />
                            <LemonButton
                                size="xsmall"
                                type="primary"
                                icon={<IconThumbsDown />}
                                disabledReason={summaryHasHadFeedback ? 'Thanks for your feedback!' : undefined}
                                onClick={() => {
                                    sessionSummaryFeedback('bad')
                                }}
                            />
                        </div>
                    </div>
                </>
            ) : (
                <div className="text-center text-muted-alt">No summary available for this session</div>
            )}
        </div>
    )
}

function LoadSessionSummaryButton(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionSummaryLoading } = useValues(playerMetaLogic(logicProps))
    const { summarizeSession } = useActions(playerMetaLogic(logicProps))

    return (
        <LemonButton
            size="small"
            type="primary"
            icon={<IconMagicWand />}
            fullWidth={true}
            data-attr="load-session-summary"
            disabledReason={sessionSummaryLoading ? 'Loading...' : undefined}
            onClick={summarizeSession}
        >
            Use AI to summarise this session
        </LemonButton>
    )
}

export function PlayerSidebarSessionSummary(): JSX.Element | null {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionSummary, sessionSummaryLoading } = useValues(playerMetaLogic(logicProps))

    return (
        <>
            {/* TODO: Uncomment after testing */}
            {/* <FlaggedFeature flag={FEATURE_FLAGS.AI_SESSION_SUMMARY} match={true}> */}
            <div className="rounded border bg-surface-primary px-2 py-1">
                {/* <h2>AI Session Summary</h2> */}
                {sessionSummaryLoading ? (
                    <>
                        Thinking... <Spinner />{' '}
                    </>
                ) : sessionSummary ? (
                    <SessionSummary />
                ) : (
                    <LoadSessionSummaryButton />
                )}
            </div>
            {/* </FlaggedFeature> */}
        </>
    )
}
