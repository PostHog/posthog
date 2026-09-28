import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowRight, IconCheck, IconChevronRight, IconMicrophone } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { REMIND_OPTIONS, SEND_OPTIONS } from './todayFixtures'
import { TodayFlowDrawer } from './TodayFlowDrawer'
import { todayFlowLogic } from './todayFlowLogic'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayScenarioEvidence } from './todayTypes'

const WORD_DELAY_MS = 45
const FIRST_WORD_MS = 520

function TodayLoadingDots(): JSX.Element {
    return (
        <span className="TodayLoadingDots" aria-hidden>
            <i />
            <i />
            <i />
        </span>
    )
}

function cardBadge(
    evidence: TodayScenarioEvidence,
    state: { landed: boolean; today: boolean; sentTo?: string; reminder?: string; ready: boolean }
): { tone: string; label: string } | null {
    if (state.landed) {
        return { tone: 'landed', label: `✓ ${evidence.done}` }
    }
    if (state.today) {
        return { tone: 'today', label: 'In Today' }
    }
    if (state.sentTo) {
        return { tone: 'sent', label: `In ${SEND_OPTIONS.find((option) => option.id === state.sentTo)?.label}` }
    }
    if (state.reminder) {
        const label = REMIND_OPTIONS.find((option) => option.id === state.reminder)?.label ?? ''
        return { tone: 'reminder', label: `Reminder ${label.toLowerCase()}` }
    }
    return state.ready ? { tone: 'ready', label: 'Ready to look at' } : null
}

function TodayMeter(): JSX.Element | null {
    const { scenario, readyEvidenceIds, readyImpact, targetReached, landedIds } = useValues(todayFlowLogic)
    const target = scenario.target
    if (!target) {
        return null
    }
    const levers = scenario.evidence.filter((evidence) => evidence.impact)
    const total = levers.reduce((sum, evidence) => sum + (evidence.impact ?? 0), 0)
    const scale = Math.max(target.goal, 1 + total) + 0.1 - 1
    return (
        <div className="TodayMeter">
            <div className="TodayMeter__head">
                <div>
                    <div className="Today__label">{target.label}</div>
                    <strong translate="no">
                        {(1 + readyImpact).toFixed(2)}
                        <small>×</small>
                    </strong>
                </div>
                {targetReached ? (
                    <span className="TodayMeter__badge">
                        <IconCheck />
                        Target reached
                    </span>
                ) : (
                    <span className="Today__label">{`${readyEvidenceIds.length} of ${levers.length} levers found`}</span>
                )}
            </div>
            <div className="TodayMeter__track">
                {levers.map((evidence) => (
                    <span
                        key={evidence.id}
                        className="TodayMeter__segment"
                        data-ready={readyEvidenceIds.includes(evidence.id)}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={
                            {
                                width: `${((evidence.impact ?? 0) / scale) * 100}%`,
                                '--segment-color': evidence.color,
                            } as React.CSSProperties
                        }
                    />
                ))}
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <span className="TodayMeter__goal" style={{ left: `${((target.goal - 1) / scale) * 100}%` }}>
                    <span>{`${target.goal}× goal`}</span>
                </span>
            </div>
            <div className="TodayMeter__legend">
                {levers.map((evidence) => (
                    <div
                        key={evidence.id}
                        data-ready={readyEvidenceIds.includes(evidence.id)}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ '--segment-color': evidence.color } as React.CSSProperties}
                    >
                        {landedIds.includes(evidence.id) ? <IconCheck className="size-3.5" /> : <i />}
                        <span>{evidence.lever}</span>
                        <code>{`+${evidence.impact?.toFixed(2)}×`}</code>
                    </div>
                ))}
            </div>
        </div>
    )
}

function TodayFlowCard({ evidence, index }: { evidence: TodayScenarioEvidence; index: number }): JSX.Element {
    const { scenario, readyEvidenceIds, landedIds, sentTo, reminders, voice } = useValues(todayFlowLogic)
    const { openEvidence } = useActions(todayFlowLogic)
    const { todayItems } = useValues(todayLogic)
    const ready = readyEvidenceIds.includes(evidence.id)
    const badge = cardBadge(evidence, {
        ready,
        landed: landedIds.includes(evidence.id),
        today: todayItems.some((item) => item.evidenceId === evidence.id),
        sentTo: sentTo[evidence.id],
        reminder: reminders[evidence.id],
    })
    return (
        <button
            type="button"
            className="TodayFlowCard"
            disabled={!ready}
            aria-busy={!ready}
            data-ready={ready}
            data-reference={voice ? `A${index + 1}` : undefined}
            data-attr="today-flow-card"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--card-color': evidence.color, '--index': index } as React.CSSProperties}
            onClick={() => openEvidence(evidence.id)}
        >
            <span className="TodayFlowCard__reference">{`A${index + 1}`}</span>
            <span className="TodayFlowCard__top">
                <span className="TodayTile">
                    <TodayIcon scenario={scenario.id} />
                </span>
                <span>{evidence.eyebrow}</span>
                {ready ? badge && <em data-tone={badge.tone}>{badge.label}</em> : <TodayLoadingDots />}
            </span>
            {ready ? (
                <>
                    <span className="TodayFlowCard__body">
                        <strong>{evidence.title}</strong>
                        <p>{evidence.summary}</p>
                    </span>
                    <span className="TodayFlowCard__bars" aria-hidden>
                        {evidence.steps.map((step, stepIndex) => (
                            <i
                                key={step.label}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    width: `${step.width}%`,
                                    opacity: 0.9 - stepIndex * 0.18,
                                    animationDelay: `${stepIndex * 80}ms`,
                                }}
                            />
                        ))}
                    </span>
                    <span className="TodayFlowCard__foot">
                        <span>{evidence.source}</span>
                        {evidence.impact !== undefined && <code>{`+${evidence.impact.toFixed(2)}×`}</code>}
                        <IconChevronRight />
                    </span>
                </>
            ) : (
                <span className="TodayFlowCard__skeleton" aria-hidden>
                    <i />
                    <i />
                    <i />
                </span>
            )}
        </button>
    )
}

function TodayFlowAsk(): JSX.Element {
    const { voice } = useValues(todayFlowLogic)
    const { toggleVoice, setVoice } = useActions(todayFlowLogic)
    const { askQuestion } = useActions(todayLogic)
    const { currentConversation } = useValues(todayLogic)
    const [followUp, setFollowUp] = useState(currentConversation?.question ?? '')

    useEffect(() => {
        if (!voice) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                setVoice(false)
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [voice, setVoice])

    return (
        <form
            className="TodayFlowAsk"
            data-voice={voice}
            onSubmit={(event) => {
                event.preventDefault()
                const trimmed = followUp.trim()
                if (trimmed) {
                    askQuestion(trimmed)
                    setFollowUp('')
                }
            }}
        >
            {voice ? (
                <span className="TodayFlowAsk__listening">
                    Listening. Say “A1”, “A2”, or “A3” to point at evidence.
                </span>
            ) : (
                <>
                    <input
                        value={followUp}
                        placeholder="Ask a follow-up…"
                        aria-label="Ask a follow-up"
                        data-attr="today-flow-follow-up"
                        onChange={(event) => setFollowUp(event.target.value)}
                    />
                    {followUp.trim() && (
                        <button type="submit" className="TodaySend" aria-label="Ask PostHog AI">
                            <IconArrowRight />
                        </button>
                    )}
                </>
            )}
            <button
                type="button"
                className="TodayVoice"
                aria-pressed={voice}
                aria-label={voice ? 'Stop talking' : 'Talk it through'}
                data-attr="today-flow-voice"
                onClick={toggleVoice}
            >
                {voice ? (
                    Array.from({ length: 7 }, (_, bar) => (
                        // eslint-disable-next-line react/forbid-dom-props
                        <i key={bar} style={{ '--bar': bar } as React.CSSProperties} />
                    ))
                ) : (
                    <IconMicrophone />
                )}
            </button>
        </form>
    )
}

export function TodayFlowThread(): JSX.Element {
    const { phase, thoughts, thoughtIndex, scenario, voice, openEvidence } = useValues(todayFlowLogic)
    const { currentConversation } = useValues(todayLogic)
    const question = currentConversation?.question ?? scenario.prompt

    if (phase !== 'results') {
        return (
            <div className="TodayThread Today__page" data-layout="stage">
                <h1 className="TodayThread__question">{question}</h1>
                <div className="TodayThread__status" aria-live="polite">
                    {phase === 'thinking' && <span key={thoughtIndex}>{thoughts[thoughtIndex]?.text}</span>}
                </div>
            </div>
        )
    }

    const words = scenario.conclusion.split(' ')
    // The drawer sits outside the animated page: a transformed ancestor would confine its fixed position.
    return (
        <>
            <div className={cn('TodayThread Today__page', voice && 'TodayFlow--voice')} data-layout="board">
                <h1 className="TodayThread__question">{question}</h1>
                <div className="TodayThread__results">
                    <div className="Today__label">Working theory</div>
                    <h2 aria-label={scenario.conclusion}>
                        {words.map((word, index) => (
                            <span
                                key={index}
                                aria-hidden
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ animationDelay: `${FIRST_WORD_MS + index * WORD_DELAY_MS}ms` }}
                            >
                                {word}&nbsp;
                            </span>
                        ))}
                    </h2>
                    <p>I’m gathering the evidence behind each part. Open anything that is ready.</p>
                </div>
                <TodayMeter />
                <div className="TodayFlowGrid">
                    {scenario.evidence.map((evidence, index) => (
                        <TodayFlowCard key={evidence.id} evidence={evidence} index={index} />
                    ))}
                </div>
                <TodayFlowAsk />
            </div>
            {openEvidence && <TodayFlowDrawer evidence={openEvidence} />}
        </>
    )
}
