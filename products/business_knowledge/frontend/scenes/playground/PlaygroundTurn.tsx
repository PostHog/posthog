import { memo } from 'react'

import { IconDocument, IconSearch } from '@posthog/icons'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { Thread } from 'products/posthog_ai/frontend/api/primitives'

import { type PlaygroundTurnApi, SandboxToolNameEnumApi } from '../../generated/api.schemas'
import { describeSearch } from './playgroundDisplay'

export interface PlaygroundTurnProps {
    id: string
    question: string
    /** `null` while the question is being sent and the server has not stored the turn yet. */
    turn: PlaygroundTurnApi | null
}

export const PlaygroundTurn = memo(function PlaygroundTurn({ id, question, turn }: PlaygroundTurnProps): JSX.Element {
    const run = turn?.run ?? null
    const isRunning = turn === null || run?.status === 'running'
    const error = turn?.error ?? run?.error ?? null

    return (
        <>
            <Thread.Message type="human">
                <Thread.Markdown content={question} id={`${id}-question`} />
            </Thread.Message>
            {run?.searches.map((search, index) => {
                const label = describeSearch(search)
                return (
                    <Thread.Activity
                        key={`${search.tool}-${index}`}
                        id={`${id}-search-${index}`}
                        title={label.title}
                        subtitle={label.subtitle}
                        status="completed"
                        icon={
                            search.tool === SandboxToolNameEnumApi.BusinessKnowledgeDocumentsSearch ? (
                                <IconSearch />
                            ) : (
                                <IconDocument />
                            )
                        }
                        animate={false}
                        showCompletionIcon={false}
                    />
                )
            })}
            {isRunning ? (
                <Thread.Reasoning
                    content="Looking through business knowledge"
                    completed={false}
                    id={`${id}-running`}
                    showCompletionIcon={false}
                    animate
                />
            ) : null}
            {run?.status === 'completed' && run.reply ? (
                <Thread.Message type="ai" wrapperClassName="max-w-4/5">
                    <LemonMarkdown disableImages>{run.reply}</LemonMarkdown>
                    {run.sources.length > 0 ? (
                        <div className="mt-2 flex flex-col gap-1 border-t pt-2">
                            <span className="text-xs font-semibold text-secondary">Sources</span>
                            <ul className="m-0 flex min-w-0 list-none flex-col gap-1 p-0 text-xs">
                                {run.sources.map((source, index) => (
                                    <li key={`${source.ref}-${index}`} className="break-words">
                                        <span className="font-semibold">{source.ref}</span>
                                        <span className="text-secondary"> {source.excerpt}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    ) : null}
                </Thread.Message>
            ) : null}
            {run?.docs_search_called ? (
                <Thread.Failure
                    id={`${id}-docs-search`}
                    content="This answer searched PostHog documentation, which this playground does not allow. Ask again."
                />
            ) : null}
            {error ? <Thread.Failure id={`${id}-error`} content={error} /> : null}
        </>
    )
})
