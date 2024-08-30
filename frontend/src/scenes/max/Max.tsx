import './Max.scss'

import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { HedgehogBuddyStatic } from 'lib/components/HedgehogBuddy/HedgehogBuddyRender'
import React, { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'

import { maxLogic } from './maxLogic'

export const scene: SceneExport = {
    component: Max,
    logic: maxLogic,
}

function Message({
    role,
    children,
    className,
}: React.PropsWithChildren<{ role: 'user' | 'assistant'; className?: string }>): JSX.Element {
    return (
        <div
            className={clsx(
                'border p-2 rounded',
                role === 'user' ? 'bg-accent-3000 self-end' : 'bg-bg-light self-start w-2/3',
                className
            )}
        >
            {children}
        </div>
    )
}

export function Max(): JSX.Element {
    const { user } = useValues(userLogic)
    const { thread, threadLoading } = useValues(maxLogic)
    const { askMax } = useActions(maxLogic)

    const [question, setQuestion] = useState('')

    return (
        <>
            <div className="flex flex-col gap-4 grow p-4">
                {thread.map((message, index) => {
                    if (message.role === 'user' || typeof message.content === 'string') {
                        return (
                            <Message key={index} role={message.role}>
                                {message.content || <i>No text</i>}
                            </Message>
                        )
                    }

                    const query = {
                        kind: NodeKind.InsightVizNode,
                        source: message.content.answer,
                    }

                    return (
                        <React.Fragment key={index}>
                            <Message role={message.role}>
                                <ul className="list-disc ml-4">
                                    {message.content.reasoning_steps.map((step, index) => (
                                        <li key={index}>{step}</li>
                                    ))}
                                </ul>
                            </Message>
                            <Message role={message.role}>
                                {!threadLoading && <Query query={query} readOnly embedded />}
                                <LemonButton
                                    className="mt-4 w-fit"
                                    type="primary"
                                    to={`/insights/new#filters=${JSON.stringify(
                                        queryNodeToFilter(message.content.answer)
                                    )}`}
                                    targetBlank
                                >
                                    Edit Query
                                </LemonButton>
                            </Message>
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
            <div className="relative flex items-start px-4">
                <div className="flex -ml-2.5 -mt-2">
                    <HedgehogBuddyStatic
                        accessories={user?.hedgehog_config?.accessories}
                        color={user?.hedgehog_config?.color}
                        size={80}
                        waveOnAppearance
                    />
                </div>
                <LemonInput
                    value={question}
                    onChange={(value) => setQuestion(value)}
                    placeholder="Hey, I'm Max! What would you like to know about your product?"
                    fullWidth
                    size="large"
                    autoFocus
                    onPressEnter={() => {
                        askMax(question)
                        setQuestion('')
                    }}
                    disabled={threadLoading}
                    suffix={
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                askMax(question)
                                setQuestion('')
                            }}
                            disabledReason={threadLoading ? 'Thinking…' : undefined}
                        >
                            Ask Max
                        </LemonButton>
                    }
                />
            </div>
        </>
    )
}
