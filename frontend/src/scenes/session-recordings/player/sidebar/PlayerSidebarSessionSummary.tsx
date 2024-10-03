import { IconMagicWand, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { playerMetaLogic } from 'scenes/session-recordings/player/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

function SessionSummary(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionSummary, summaryHasHadFeedback } = useValues(playerMetaLogic(logicProps))
    const { sessionSummaryFeedback } = useActions(playerMetaLogic(logicProps))

    return (
        <div>
            {sessionSummary.content}
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
                <div className="rounded border bg-bg-light m-2 px-2 py-1">
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
