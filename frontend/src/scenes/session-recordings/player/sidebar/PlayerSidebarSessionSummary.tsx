import { IconChevronRight, IconFolderOpen, IconMagicWand, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from 'lib/ui/DropdownMenu/DropdownMenu'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useState } from 'react'

type FilterType = 'all' | 'errors' | 'important'

const FILTER_TYPES: Record<FilterType, { label: string }> = {
    all: { label: 'Show full journey' },
    errors: { label: 'Show only errors' },
    important: { label: 'Show only important events' },
}

function formatMsIntoTime(ms: number): string {
    const seconds = Math.floor(ms / 1000)
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    const remainingSeconds = seconds % 60

    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`
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
        // TODO Change with a proper limited instead of manual rem
        <div className="flex flex-col" style={{ maxWidth: '24rem' }}>
            {sessionSummary ? (
                <>
                    <div className="text-sm break-words">
                        {sessionSummary.content.summary}
                    </div>

                    <div>
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <LemonButton
                                    type="primary"
                                    className="mt-2"
                                    icon={<IconFolderOpen />}
                                >
                                    {FILTER_TYPES[filterType].label}
                                    <IconChevronRight className="text-secondary rotate-90 group-data-[state=open]/button-root:rotate-270 transition-transform duration-200 prefers-reduced-motion:transition-none" />
                                </LemonButton>

                                {/* <Button.Root>
                                    <Button.Icon>
                                        <IconFolderOpen className="text-tertiary" />
                                    </Button.Icon>
                                    <Button.Label>
                                        {FILTER_TYPES[filterType].label}
                                    </Button.Label>
                                    <Button.Icon size="sm">
                                        <IconChevronRight className="text-secondary rotate-90 group-data-[state=open]/button-root:rotate-270 transition-transform duration-200 prefers-reduced-motion:transition-none" />
                                    </Button.Icon>
                                </Button.Root> */}
                            </DropdownMenuTrigger>

                            <DropdownMenuContent loop align="start">
                                {Object.entries(FILTER_TYPES).map(([key, { label }]) => (
                                    <DropdownMenuItem key={key} asChild className="cursor-pointer hover:bg-primary-alt-highlight">
                                        {/* <Button.Root onClick={() => setFilterType(key as FilterType)}>
                                            <Button.Label>{label}</Button.Label>
                                        </Button.Root> */}
                                        <LemonButton
                                            type="primary"
                                            className="mt-2"
                                            onClick={() => setFilterType(key as FilterType)}
                                        >
                                            {label}
                                            <IconChevronRight className="text-secondary rotate-90 group-data-[state=open]/button-root:rotate-270 transition-transform duration-200 prefers-reduced-motion:transition-none" />
                                        </LemonButton>
                                    </DropdownMenuItem>
                                ))}
                            </DropdownMenuContent>
                        </DropdownMenu>

                        <div>
                            {filteredEvents?.map((event, index) => (
                                <div
                                    key={index}
                                    className={`border-b cursor-pointer py-2 px-2 hover:bg-primary-alt-highlight ${event.error ? 'bg-danger-highlight' : ''}`}
                                    onClick={() => {
                                        seekToTime(event.milliseconds_since_start)
                                    }}
                                >
                                    <div className="flex flex-row gap-2">
                                        <span className="text-muted-alt shrink-0 min-w-[4rem] font-mono text-xs">
                                            {formatMsIntoTime(event.milliseconds_since_start)}<br />
                                        </span>
                                        <span className="text-xs break-words">{event.description}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <LemonDivider dashed={true} />
                    <div className="text-right">
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
                <div className="text-center text-muted-alt">
                    No summary available for this session
                </div>
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
