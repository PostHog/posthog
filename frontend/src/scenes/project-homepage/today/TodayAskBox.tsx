import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowRight } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { todayLogic } from './todayLogic'

/** Sends the question to PostHog AI. */
export function TodayAskBox({ compact = false }: { compact?: boolean }): JSX.Element {
    const { sentQuestion } = useValues(todayLogic)
    const { askQuestion } = useActions(todayLogic)
    const [question, setQuestion] = useState('')

    return (
        <>
            <form
                className={cn('TodayAsk', compact && 'TodayAsk--compact')}
                onSubmit={(event) => {
                    event.preventDefault()
                    const trimmed = question.trim()
                    if (trimmed) {
                        askQuestion(trimmed)
                        setQuestion('')
                    }
                }}
            >
                <input
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    placeholder="what would you like to know?"
                    aria-label="Ask PostHog"
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
            {sentQuestion && <div className="TodayAsk__sent">{`Asked: “${sentQuestion}”`}</div>}
        </>
    )
}
