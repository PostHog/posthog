import { IconMagicWand } from '@posthog/icons'
import { BindLogic, useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { useState } from 'react'
import { Thread } from 'scenes/max/Thread'

import { queryAILogic } from './queryAILogic'

interface QueryAIProps {
    codeEditorKey: string
}

export function QueryAI({ codeEditorKey }: QueryAIProps): JSX.Element {
    return (
        <BindLogic logic={queryAILogic} props={{ conversationId: null, codeEditorKey }}>
            <QueryAIInstance />
        </BindLogic>
    )
}

export function QueryAIInstance(): JSX.Element {
    const { question, threadLoading, threadGrouped, animationId } = useValues(queryAILogic)
    const { setQuestion, askQueryAI } = useActions(queryAILogic)
    const [hasSubmitted, setHasSubmitted] = useState(false)

    const handleSubmit = (): void => {
        if (!question) {
            return
        }
        askQueryAI(question)
        setHasSubmitted(true)
    }

    return (
        <div className="flex flex-col pt-2 gap-2 h-full">
            {!hasSubmitted && (
                <div className="flex gap-2 pl-2 pr-2">
                    <LemonInput
                        className="grow"
                        prefix={<IconMagicWand />}
                        value={question}
                        onPressEnter={handleSubmit}
                        onChange={(value) => setQuestion(value)}
                        placeholder="What do you want to know? How would you like to tweak the query?"
                        maxLength={400}
                    />
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        disabledReason={!question ? 'Provide a prompt first' : null}
                        tooltipPlacement="left"
                        loading={threadLoading}
                    >
                        Think
                    </LemonButton>
                </div>
            )}

            {hasSubmitted && (
                <div className="flex flex-col h-full">
                    <div className="flex-grow overflow-auto pb-14">
                        {threadGrouped.length > 0 && (
                            <Thread animationId={animationId} threadGrouped={threadGrouped} onlySummary={true} />
                        )}
                    </div>
                    <div className="flex gap-2 pt-2 pr-2 pl-2 sticky bottom-2 z-10">
                        <LemonInput
                            className="grow"
                            prefix={<IconMagicWand />}
                            value={question}
                            onPressEnter={handleSubmit}
                            onChange={(value) => setQuestion(value)}
                            placeholder="Ask a follow-up question..."
                            maxLength={400}
                        />
                        <LemonButton
                            type="primary"
                            onClick={handleSubmit}
                            disabledReason={!question ? 'Provide a prompt first' : null}
                            tooltipPlacement="left"
                            loading={threadLoading}
                        >
                            Ask
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
