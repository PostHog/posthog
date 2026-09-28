import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowRight, IconChevronRight } from '@posthog/icons'

import { SCENARIOS } from './todayFixtures'
import { todayFlowLogic } from './todayFlowLogic'
import { TodayFlowThread } from './TodayFlowThread'
import { TodayIcon } from './TodayIcon'
import { SCENARIO_COLORS, todayLogic } from './todayLogic'
import { TodayScenarioId } from './todayTypes'

const LEAVE_MS = 260

function TodayCompose(): JSX.Element {
    const { askQuestion, startConversation } = useActions(todayLogic)
    const [prompt, setPrompt] = useState('')
    const [leaving, setLeaving] = useState(false)

    const pickScenario = (scenarioId: TodayScenarioId): void => {
        setLeaving(true)
        window.setTimeout(() => startConversation(SCENARIOS[scenarioId].prompt, scenarioId), LEAVE_MS)
    }
    const submit = (): void => {
        const trimmed = prompt.trim()
        if (trimmed) {
            askQuestion(trimmed)
            setPrompt('')
        }
    }

    return (
        <div className="TodayFlow TodayCompose Today__page" data-leaving={leaving}>
            <div className="Today__label">Suggested from your data</div>
            <h1>What should we figure out?</h1>
            <p>These questions use changes that PostHog can already see across your product.</p>
            <div className="TodaySuggestions">
                {Object.values(SCENARIOS).map((scenario, index) => (
                    <button
                        key={scenario.id}
                        type="button"
                        className="TodaySuggestion"
                        data-attr={`today-suggestion-${scenario.id}`}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={
                            {
                                '--suggestion-color': SCENARIO_COLORS[scenario.id],
                                animationDelay: `${180 + index * 70}ms`,
                            } as React.CSSProperties
                        }
                        onClick={() => pickScenario(scenario.id)}
                    >
                        <span className="TodaySuggestion__icon">
                            <TodayIcon scenario={scenario.id} />
                        </span>
                        <span>
                            <strong>{scenario.suggestion}</strong>
                            <small>{scenario.signal}</small>
                        </span>
                        <IconChevronRight />
                    </button>
                ))}
            </div>
            <form
                className="TodayComposer"
                onSubmit={(event) => {
                    event.preventDefault()
                    submit()
                }}
            >
                <textarea
                    autoFocus
                    rows={3}
                    value={prompt}
                    placeholder="Ask anything about your product…"
                    aria-label="Ask anything about your product"
                    data-attr="today-compose-input"
                    onChange={(event) => setPrompt(event.target.value)}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter' && !event.shiftKey) {
                            event.preventDefault()
                            submit()
                        }
                    }}
                />
                <div className="TodayComposer__foot">
                    <span>Answered by PostHog AI with your product data</span>
                    <button
                        type="submit"
                        className="TodaySend"
                        aria-label="Ask PostHog AI"
                        disabled={!prompt.trim()}
                        data-attr="today-compose-send"
                    >
                        <IconArrowRight />
                    </button>
                </div>
            </form>
        </div>
    )
}

export function TodayNewFlow(): JSX.Element {
    const { currentConversation, route } = useValues(todayLogic)
    if (!currentConversation) {
        return <TodayCompose />
    }
    const props = {
        conversationId: currentConversation.id,
        scenarioId: currentConversation.scenarioId,
        question: currentConversation.question,
        resumed: currentConversation.status === 'answered',
        initialEvidenceId: route.evidenceId,
    }
    return (
        <BindLogic logic={todayFlowLogic} props={props}>
            <TodayFlowThread key={`${currentConversation.id}-${route.evidenceId ?? ''}`} />
        </BindLogic>
    )
}
