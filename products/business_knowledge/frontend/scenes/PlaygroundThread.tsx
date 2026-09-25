import { useActions, useValues } from 'kea'
import { FormEvent } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'

import { businessKnowledgePlaygroundLogic } from './businessKnowledgePlaygroundLogic'

export function PlaygroundThread(): JSX.Element {
    const { chat, chatLoading, chatError, question, asking, askDisabled, askError, chatHasOpenTurn } = useValues(
        businessKnowledgePlaygroundLogic
    )
    const { setQuestion, ask } = useActions(businessKnowledgePlaygroundLogic)
    const turns = chat?.turns ?? []

    const submit = (event?: FormEvent): void => {
        event?.preventDefault()
        if (!askDisabled) {
            ask()
        }
    }

    return (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-y-auto px-1">
                {chatLoading && turns.length === 0 ? (
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-6 w-2/3" />
                        <LemonSkeleton className="h-16" />
                    </div>
                ) : null}
                {chatError ? <LemonBanner type="error">{chatError}</LemonBanner> : null}
                {!chatLoading && !chatError && turns.length === 0 ? (
                    <div className="flex flex-1 items-center justify-center px-6 text-center">
                        <p className="m-0 max-w-md text-muted">
                            Answers use only this project's business knowledge. PostHog documentation is not searched.
                        </p>
                    </div>
                ) : null}
                {turns.map((turn) => (
                    <div key={turn.id} className="flex min-w-0 flex-col gap-2">
                        <p className="m-0 ml-auto max-w-[85%] break-words rounded-lg bg-fill-highlight-100 px-3 py-2">
                            {turn.question}
                        </p>
                        {turn.error ? <LemonBanner type="error">{turn.error}</LemonBanner> : null}
                        {turn.run?.docs_search_called ? (
                            <LemonBanner type="error">
                                This answer searched PostHog documentation, which this playground does not allow. Ask
                                again.
                            </LemonBanner>
                        ) : null}
                        {turn.run?.status === 'running' || (turn.run === null && !turn.error) ? (
                            <p className="m-0 text-muted">Looking through business knowledge.</p>
                        ) : null}
                        {turn.run?.status === 'completed' && turn.run.reply ? (
                            <p className="m-0 max-w-180 break-words whitespace-pre-wrap">{turn.run.reply}</p>
                        ) : null}
                        {turn.run?.error ? <LemonBanner type="error">{turn.run.error}</LemonBanner> : null}
                        {turn.run && turn.run.sources.length > 0 ? (
                            <ul className="m-0 flex min-w-0 max-w-180 list-disc flex-col gap-2 pl-5">
                                {turn.run.sources.map((source) => (
                                    <li key={`${source.ref}-${source.excerpt}`} className="break-words">
                                        <span className="font-semibold">{source.ref}</span>
                                        <span>: {source.excerpt}</span>
                                    </li>
                                ))}
                            </ul>
                        ) : null}
                        {turn.run && turn.run.searches.length > 0 ? (
                            <ul className="m-0 flex min-w-0 max-w-180 list-none flex-col gap-1 p-0 text-muted">
                                {turn.run.searches.map((search) => (
                                    <li key={`${search.tool}-${search.input}`} className="break-all">
                                        {search.tool}: {search.input}
                                    </li>
                                ))}
                            </ul>
                        ) : null}
                    </div>
                ))}
            </div>
            {askError ? (
                <div className="mx-auto w-full max-w-180 shrink-0 px-1 pb-2">
                    <LemonBanner type="error">{askError}</LemonBanner>
                </div>
            ) : null}
            <form className="mx-auto w-full max-w-180 shrink-0 px-1 pb-3" onSubmit={submit}>
                <div className="rounded-lg border border-primary bg-surface-primary p-2">
                    <LemonTextArea
                        value={question}
                        onChange={setQuestion}
                        onPressEnter={() => submit()}
                        placeholder="Ask about this project's business knowledge"
                        minRows={2}
                        maxRows={8}
                        hideFocus
                        className="border-0 bg-transparent"
                        disabled={asking || chatHasOpenTurn}
                        // pinned: autocapture / Playwright key. Do not rename.
                        data-attr="business-knowledge-playground-question"
                    />
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            size="small"
                            icon={<IconArrowRight />}
                            disabled={askDisabled}
                            disabledReason={
                                chatHasOpenTurn
                                    ? 'Wait for this answer to finish.'
                                    : askDisabled && !asking
                                      ? 'Enter a question first.'
                                      : undefined
                            }
                            loading={asking}
                            // pinned: autocapture / Playwright key. Do not rename.
                            data-attr="business-knowledge-playground-ask"
                        >
                            Ask
                        </LemonButton>
                    </div>
                </div>
            </form>
        </div>
    )
}
