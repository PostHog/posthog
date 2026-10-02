import { useActions } from 'kea'
import { useState } from 'react'

import { IconArrowRight } from '@posthog/icons'

import { todayLogic } from './todayLogic'

/** Sends the question to PostHog AI with the briefing as context. PostHog AI answers in a new chat under Spaces. */
export function TodayAskBox(): JSX.Element {
    const { askAi } = useActions(todayLogic)
    const [question, setQuestion] = useState('')

    return (
        <form
            className="TodayAsk"
            onSubmit={(event) => {
                event.preventDefault()
                const trimmed = question.trim()
                if (trimmed) {
                    askAi(trimmed, 'ask_box')
                    setQuestion('')
                }
            }}
        >
            <input
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="What would you like to know?"
                aria-label="Ask PostHog AI"
                data-attr="today-ask-input"
            />
            <button
                type="submit"
                className="TodaySend"
                aria-label="Send question"
                disabled={!question.trim()}
                data-attr="today-ask-send"
            >
                <IconArrowRight />
            </button>
        </form>
    )
}
