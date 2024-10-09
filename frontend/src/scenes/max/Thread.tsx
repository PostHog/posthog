import { LemonButton, Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import React from 'react'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind } from '~/queries/schema'

import { maxLogic } from './maxLogic'

export function Thread(): JSX.Element | null {
    const { thread, threadLoading } = useValues(maxLogic)

    return (
        <div className="flex flex-col items-stretch w-full max-w-200 self-center gap-2 grow m-4">
            {thread.map((message, index) => {
                if (message.role === 'user' || typeof message.content === 'string') {
                    return (
                        <Message
                            key={index}
                            role={message.role}
                            className={message.status === 'error' ? 'border-danger' : undefined}
                        >
                            {message.content || <i>No text</i>}
                        </Message>
                    )
                }

                const query = {
                    kind: NodeKind.InsightVizNode,
                    source: message.content?.answer,
                }

                return (
                    <React.Fragment key={index}>
                        {message.content?.reasoning_steps && (
                            <Message role={message.role}>
                                <ul className="list-disc ml-4">
                                    {message.content.reasoning_steps.map((step, index) => (
                                        <li key={index}>{step}</li>
                                    ))}
                                </ul>
                            </Message>
                        )}
                        {message.status === 'completed' && message.content?.answer && (
                            <Message role={message.role}>
                                <div className="h-96 flex">
                                    <Query query={query} readOnly embedded />
                                </div>
                                <LemonButton
                                    className="mt-4 w-fit"
                                    type="primary"
                                    to={urls.insightNew(undefined, undefined, {
                                        kind: NodeKind.InsightVizNode,
                                        source: message.content.answer,
                                    } as InsightVizNode)}
                                    sideIcon={<IconOpenInNew />}
                                    targetBlank
                                >
                                    Open as new insight
                                </LemonButton>
                            </Message>
                        )}
                    </React.Fragment>
                )
            })}
            {threadLoading && (
                <Message role="assistant" className="w-fit select-none">
                    <div className="flex items-center gap-2">
                        Let me think…
                        <Spinner className="text-xl" />
                    </div>
                </Message>
            )}
        </div>
    )
}

function Message({
    role,
    children,
    className,
}: React.PropsWithChildren<{ role: 'user' | 'assistant'; className?: string }>): JSX.Element {
    if (role === 'user') {
        return <h2 className={clsx('mt-1 mb-3 text-2xl font-medium', className)}>{children}</h2>
    }

    return <div className={clsx('border p-2 rounded bg-bg-light', className)}>{children}</div>
}
