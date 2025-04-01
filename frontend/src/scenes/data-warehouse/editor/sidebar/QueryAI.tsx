import { useActions, useValues } from 'kea'
import { QuestionInputComponent } from 'scenes/max/QuestionInput'
import { Thread } from 'scenes/max/Thread'

import { queryAILogic } from './queryAILogic'

export function QueryAI(): JSX.Element {
    const { question, threadLoading, threadGrouped, animationId, initialState } = useValues(queryAILogic)
    const { setQuestion, askQueryAI } = useActions(queryAILogic)

    const handleSubmit = (): void => {
        if (!question) {
            return
        }
        askQueryAI(question)
    }

    return (
        <div className="flex flex-col pt-2 gap-2 h-full">
            {initialState && (
                <div className="flex gap-2 pl-2 pr-2">
                    <QuestionInputComponent
                        onChange={(value) => setQuestion(value)}
                        placeholder={threadLoading ? 'Thinking…' : 'Ask Max to write a query for you'}
                        value={question}
                        onSubmit={handleSubmit}
                        isLoading={threadLoading}
                        inputDisabled={threadLoading}
                        buttonDisabledReason={threadLoading ? "Let's bail" : undefined}
                    />
                </div>
            )}

            {!initialState && (
                <div className="flex flex-col h-full">
                    <div className="flex-grow overflow-auto pb-14">
                        {threadGrouped.length > 0 && (
                            <Thread animationId={animationId} threadGrouped={threadGrouped} onlySummary={true} />
                        )}
                    </div>
                    <div className="flex gap-2 pt-2 pr-2 pl-2 sticky bottom-2 z-10">
                        <QuestionInputComponent
                            onChange={(value) => setQuestion(value)}
                            placeholder={threadLoading ? 'Thinking…' : 'Ask follow up'}
                            value={question}
                            onSubmit={handleSubmit}
                            isLoading={threadLoading}
                            isFloating={true}
                            buttonDisabledReason={threadLoading ? "Let's bail" : undefined}
                        />
                    </div>
                </div>
            )}
        </div>
    )
}
