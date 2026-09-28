import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonBanner, LemonDivider } from '@posthog/lemon-ui'

import { Composer, RunLogSkeleton, Welcome } from 'products/posthog_ai/frontend/api/primitives'

import { businessKnowledgePlaygroundLogic } from './businessKnowledgePlaygroundLogic'
import { PlaygroundTurn } from './PlaygroundTurn'

export function PlaygroundThread(): JSX.Element {
    const { chat, chatId, chatLoading, chatError, question, asking, askError, chatHasOpenTurn, pendingQuestion } =
        useValues(businessKnowledgePlaygroundLogic)
    const { setQuestion, ask } = useActions(businessKnowledgePlaygroundLogic)
    const scrollRef = useRef<HTMLDivElement>(null)
    const turns = chat?.turns ?? []
    const lastRun = turns.at(-1)?.run
    const isEmpty = !chatLoading && !chatError && turns.length === 0 && pendingQuestion === null

    // Follow the newest turn the way the PostHog AI thread sticks to the bottom.
    useEffect(() => {
        const node = scrollRef.current
        if (node) {
            node.scrollTop = node.scrollHeight
        }
    }, [chatId, turns.length, lastRun?.status, lastRun?.searches.length, pendingQuestion])

    const composer = (
        <Composer.Root
            value={question}
            onChange={setQuestion}
            onSubmit={ask}
            loading={asking && !chatHasOpenTurn}
            disabledReason={chatHasOpenTurn ? 'Wait for this answer to finish.' : undefined}
        >
            {askError ? (
                <Composer.Banner>
                    <LemonBanner type="error" className="mb-2">
                        {askError}
                    </LemonBanner>
                </Composer.Banner>
            ) : null}
            <Composer.Frame>
                <Composer.Field>
                    <Composer.Placeholder>Ask about this project's business knowledge</Composer.Placeholder>
                    <Composer.Textarea
                        autoFocus
                        // pinned: autocapture / Playwright key. Do not rename.
                        data-attr="business-knowledge-playground-question"
                    />
                </Composer.Field>
            </Composer.Frame>
            <Composer.Submit
                tooltip="Ask"
                // pinned: autocapture / Playwright key. Do not rename.
                data-attr="business-knowledge-playground-ask"
            />
        </Composer.Root>
    )

    if (isEmpty) {
        return (
            <div className="flex min-h-0 min-w-0 flex-1 flex-col items-center justify-center overflow-y-auto p-4">
                <div className="flex w-full max-w-2xl flex-col items-center gap-4">
                    <Welcome
                        headline="Ask about your business knowledge"
                        subheadline="Answers use only this project's business knowledge. PostHog documentation is not searched."
                    />
                    {composer}
                </div>
            </div>
        )
    }

    return (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
                {chatLoading && turns.length === 0 ? (
                    <RunLogSkeleton rowClassName="px-4" />
                ) : (
                    <div className="mx-auto flex w-full max-w-180 flex-col gap-1.5 px-4 py-4">
                        {chatError ? <LemonBanner type="error">{chatError}</LemonBanner> : null}
                        {turns.map((turn) => (
                            <PlaygroundTurn key={turn.id} id={turn.id} question={turn.question} turn={turn} />
                        ))}
                        {pendingQuestion !== null ? (
                            <PlaygroundTurn id="pending" question={pendingQuestion} turn={null} />
                        ) : null}
                    </div>
                )}
            </div>
            <div className="shrink-0 px-4 pb-4">
                <LemonDivider className="mt-0 mb-4" />
                <div className="mx-auto w-full max-w-180">{composer}</div>
            </div>
        </div>
    )
}
