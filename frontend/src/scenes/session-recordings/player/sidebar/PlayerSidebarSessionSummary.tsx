import { IconFilter, IconMagicWand, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonBanner, LemonMenu, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useState } from 'react'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { SessionKeyEvent } from '../player-meta/types'

function formatEventMetaInfo(event: SessionKeyEvent): JSX.Element {
    return (
        <pre className="m-0 p-0 font-mono text-xs whitespace-pre">
            {`Event: ${event.event}
Type: ${event.event_type || 'N/A'}
Importance: ${(event.importance * 100).toFixed(0)}%
Window ID: ${event.window_id}
Tags:
  Where: ${event.tags.where.join(', ')}
  What: ${event.tags.what.join(', ')}`}
        </pre>
    )
}

type FilterType = 'all' | 'errors' | 'important'

const FILTER_TYPES: Record<FilterType, { label: string }> = {
    all: { label: 'Show full journey' },
    errors: { label: 'Show only failed steps' },
    important: { label: 'Show only important steps' },
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

function SessionSummary(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)
    const { sessionSummary, summaryHasHadFeedback } = useValues(playerMetaLogic(logicProps))
    const { sessionSummaryFeedback } = useActions(playerMetaLogic(logicProps))
    const [filterType, setFilterType] = useState<FilterType>('all')

    const filteredEvents = sessionSummary?.content.key_events.filter((event) => {
        if (filterType === 'errors') {
            return event.error
        }
        if (filterType === 'important') {
            return event.importance >= 0.7
        }
        return true
    })

    return (
        <div className="flex flex-col xl:max-w-96">
            {sessionSummary ? (
                <>
                    <LemonBanner className="mb-3" type="info" action={undefined} onClose={undefined}>
                        <div className="text-sm break-words py-1 px-1 font-normal">
                            {sessionSummary.content.summary}
                        </div>
                    </LemonBanner>

                    <div>
                        <LemonMenu
                            items={Object.entries(FILTER_TYPES).map(([key, { label }]) => ({
                                label,
                                onClick: () => setFilterType(key as FilterType),
                            }))}
                            buttonSize="xsmall"
                        >
                            <LemonButton type="secondary" size="xsmall" icon={<IconFilter />} className="mb-3">
                                {FILTER_TYPES[filterType].label}
                            </LemonButton>
                        </LemonMenu>

                        <div>
                            {filteredEvents?.map((event, index) => (
                                <div
                                    key={index}
                                    className={`border-b cursor-pointer py-2 px-2 hover:bg-primary-alt-highlight ${
                                        event.error ? 'bg-danger-highlight' : ''
                                    }`}
                                    onClick={() => {
                                        seekToTime(event.milliseconds_since_start)
                                    }}
                                >
                                    <div className="flex flex-row gap-2">
                                        <span className="text-muted-alt shrink-0 min-w-[4rem] font-mono text-xs">
                                            {formatMsIntoTime(event.milliseconds_since_start)}
                                            <div className="flex flex-row gap-2 mt-1">
                                                <Link to={event.current_url} target="_blank">
                                                    <Tooltip title={event.current_url} placement="top">
                                                        <span className="font-mono text-xs text-muted-alt">url</span>
                                                    </Tooltip>
                                                </Link>
                                                <Tooltip title={formatEventMetaInfo(event)} placement="top">
                                                    <span className="font-mono text-xs text-muted-alt">meta</span>
                                                </Tooltip>
                                            </div>
                                        </span>

                                        <span className="text-xs break-words">{event.description}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
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
            <FlaggedFeature flag={FEATURE_FLAGS.AI_SESSION_SUMMARY} match={true}>
                <div className="rounded border bg-surface-primary px-2 py-1">
                    <h2>AI Session Summary</h2>
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
            </FlaggedFeature>
        </>
    )
}
