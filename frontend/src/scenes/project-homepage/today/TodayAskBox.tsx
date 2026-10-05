import { useActions } from 'kea'
import { useRef, useState } from 'react'

import { Composer, QuillComposerLayout, QuillComposerSendButton } from 'products/posthog_ai/frontend/api/primitives'

import { todayLogic } from './todayLogic'

/** Sends the question to PostHog AI with the briefing as context. PostHog AI answers in a new chat under Spaces. */
export function TodayAskBox(): JSX.Element {
    const { askAi } = useActions(todayLogic)
    const [question, setQuestion] = useState('')
    const groupRef = useRef<HTMLDivElement>(null)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    return (
        <div className="TodayAsk" data-quill>
            <Composer.Root
                value={question}
                onChange={setQuestion}
                onSubmit={() => {
                    const trimmed = question.trim()
                    if (trimmed) {
                        askAi(trimmed, 'ask_box')
                        setQuestion('')
                    }
                }}
                textAreaRef={textAreaRef}
            >
                <QuillComposerLayout
                    groupRef={groupRef}
                    textAreaRef={textAreaRef}
                    field={
                        <Composer.Field>
                            <Composer.Placeholder>What would you like to know?</Composer.Placeholder>
                            <Composer.Textarea aria-label="Ask PostHog AI" data-attr="today-ask-input" />
                        </Composer.Field>
                    }
                    send={<QuillComposerSendButton data-attr="today-ask-send" />}
                />
            </Composer.Root>
        </div>
    )
}
