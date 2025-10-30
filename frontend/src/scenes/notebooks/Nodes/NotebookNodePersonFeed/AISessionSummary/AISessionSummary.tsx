import { BindLogic, useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { pluralize } from 'lib/utils'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionSummaryComponent } from 'scenes/session-recordings/player/sidebar/PlayerSidebarSessionSummary'

import { notebookNodePersonFeedLogic } from '../notebookNodePersonFeedLogic'

export function AISessionSummary({ personId }: { personId: string }): JSX.Element | null {
    const logic = notebookNodePersonFeedLogic({ personId })
    const { canSummarize, summaries, summarizingState } = useValues(logic)

    if (!canSummarize) {
        return null
    }

    return (
        <BindLogic logic={notebookNodePersonFeedLogic} props={{ personId }}>
            <SessionSummaryComponent.Root>
                {summarizingState === 'idle' && <AISummaryIdle />}
                {summarizingState === 'loading' && <AISummaryLoading />}
                {Object.entries(summaries || {}).length > 0 && <SessionSummaryComponent.Title />}
                {Object.entries(summaries).map(([sessionId, summary]) => (
                    <BindLogic
                        key={sessionId}
                        logic={sessionRecordingPlayerLogic}
                        props={{ sessionRecordingId: sessionId }}
                    >
                        <LemonDivider className="my-4" />
                        <SessionSummaryComponent.Subtitle sessionId={sessionId} />
                        <SessionSummaryComponent.OutcomeBanner sessionSummary={summary} />
                        <SessionSummaryComponent.Segments sessionSummary={summary} />
                        <SessionSummaryComponent.Feedback />
                    </BindLogic>
                ))}
            </SessionSummaryComponent.Root>
        </BindLogic>
    )
}

function AISummaryIdle(): JSX.Element {
    const { numSessionsWithRecording } = useValues(notebookNodePersonFeedLogic)
    const { summarizeSessions } = useActions(notebookNodePersonFeedLogic)

    return (
        <div className="flex items-center justify-between">
            {numSessionsWithRecording > 0 ? (
                <AISummaryMessage
                    heading="AI Session Summary"
                    subheading={`Analyze ${pluralize(numSessionsWithRecording, 'session')} and identify patterns`}
                />
            ) : (
                <AISummaryMessage heading="AI Session Summary" subheading="No sessions with recordings found" />
            )}
            <LemonButton
                type="primary"
                icon={<IconSparkles />}
                onClick={summarizeSessions}
                disabledReason={numSessionsWithRecording === 0 ? 'No sessions with recordings found' : undefined}
                data-attr="person-feed-summarize-sessions"
            >
                Summarize Sessions
            </LemonButton>
        </div>
    )
}

function AISummaryLoading(): JSX.Element {
    const { numSummaries, numSessionsWithRecording, progressText } = useValues(notebookNodePersonFeedLogic)
    return (
        <div className="mb-4">
            <AISummaryMessage heading="Generating AI Summary" subheading={progressText} />
            <LemonProgress percent={(numSummaries / numSessionsWithRecording) * 100} />
        </div>
    )
}

function AISummaryMessage({ heading, subheading }: { heading: string; subheading: string }): JSX.Element {
    return (
        <div className="mb-2">
            <div>
                <h3 className="font-semibold mb-1">{heading}</h3>
                <div className="text-sm text-muted">{subheading}</div>
            </div>
        </div>
    )
}
