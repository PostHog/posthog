import { useActions } from 'kea'
import { useState } from 'react'

import { IconArrowRight } from '@posthog/icons'

import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

/** Sends the question to PostHog AI, which answers in a new tab. */
export function TodayAskBox(): JSX.Element {
    const { askSidePanelMax } = useActions(maxGlobalLogic)
    const [question, setQuestion] = useState('')
    const [sentQuestion, setSentQuestion] = useState<string | null>(null)

    return (
        <>
            <form
                className="TodayAsk"
                onSubmit={(event) => {
                    event.preventDefault()
                    const trimmed = question.trim()
                    if (trimmed) {
                        askSidePanelMax(trimmed)
                        setSentQuestion(trimmed)
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
            {sentQuestion && <div className="TodayAsk__sent">{`Asked PostHog AI: “${sentQuestion}”`}</div>}
        </>
    )
}
