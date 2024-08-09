import './Max.scss'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { HedgehogBuddyStatic } from 'lib/components/HedgehogBuddy/HedgehogBuddyRender'
import React, { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { Query } from '~/queries/Query/Query'
import { NodeKind, TrendsQuery } from '~/queries/schema'

import { maxLogic } from './maxLogic'

export const scene: SceneExport = {
    component: Max,
    logic: maxLogic,
}

function Message({ role, children }: React.PropsWithChildren<{ role: string }>): JSX.Element {
    return (
        <div
            className={clsx(
                'border p-2 rounded',
                role === 'user' ? 'bg-accent-3000 self-end' : 'bg-bg-light self-start w-2/3'
            )}
        >
            {children}
        </div>
    )
}

export function Max(): JSX.Element {
    const { user } = useValues(userLogic)
    const { thread } = useValues(maxLogic)
    const { askMax } = useActions(maxLogic)

    const [question, setQuestion] = useState('')

    return (
        <>
            <div className="flex flex-col gap-4 grow p-4">
                {thread.map((message, index) => {
                    if (message.role === 'user') {
                        return (
                            <Message key={index} role={message.role}>
                                {message.content || <i>No text</i>}
                            </Message>
                        )
                    }

                    const content = JSON.parse(message.content)
                    const reasoningSteps = content.reasoning_steps as string[]

                    return (
                        <React.Fragment key={index}>
                            <Message role={message.role}>
                                <ul className="list-disc ml-4">
                                    {reasoningSteps.map((step, index) => (
                                        <li key={index}>{step}</li>
                                    ))}
                                </ul>
                            </Message>
                            <Message role={message.role}>
                                <Query
                                    query={{
                                        kind: NodeKind.InsightVizNode,
                                        source: content.answer as TrendsQuery,
                                    }}
                                    readOnly
                                    embedded
                                />
                                <LemonButton className="mt-4" type="primary">
                                    Edit Query
                                </LemonButton>
                            </Message>
                        </React.Fragment>
                    )
                })}
            </div>
            <div className="relative flex items-start px-4 overflow-hidden">
                <div className="flex -ml-2.5 -mt-2 animate-rise">
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
                    suffix={
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                askMax(question)
                                setQuestion('')
                            }}
                        >
                            Ask Max
                        </LemonButton>
                    }
                />
            </div>
        </>
    )
}
