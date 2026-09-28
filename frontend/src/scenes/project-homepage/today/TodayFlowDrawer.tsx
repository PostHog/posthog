import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import {
    IconArrowRight,
    IconCheck,
    IconChevronDown,
    IconChevronRight,
    IconClock,
    IconPlus,
    IconSend,
    IconX,
} from '@posthog/icons'
import { LemonMenu } from '@posthog/lemon-ui'

import { REMIND_OPTIONS, SEND_OPTIONS } from './todayFixtures'
import { breakdownDelta, todayFlowLogic } from './todayFlowLogic'
import { todayLogic } from './todayLogic'
import { TodayScenarioEvidence } from './todayTypes'

export function TodayFlowDrawer({ evidence }: { evidence: TodayScenarioEvidence }): JSX.Element {
    const { readyRecommendationIds, landedIds, reminders, sentTo, chats, typingEvidenceId } = useValues(todayFlowLogic)
    const { closeEvidence, land, addToToday, remind, send, askAboutEvidence } = useActions(todayFlowLogic)
    const { todayItems } = useValues(todayLogic)
    const [chatQuestion, setChatQuestion] = useState('')
    const recommendationReady = readyRecommendationIds.includes(evidence.id)
    const landed = landedIds.includes(evidence.id)
    const inToday = todayItems.some((item) => item.evidenceId === evidence.id)
    const reminder = REMIND_OPTIONS.find((option) => option.id === reminders[evidence.id])
    const sent = SEND_OPTIONS.find((option) => option.id === sentTo[evidence.id])
    const messages = chats[evidence.id] ?? []
    const typing = typingEvidenceId === evidence.id
    const first = evidence.steps[0]?.value ?? ''
    const status = [
        landed ? `${evidence.done}.` : null,
        inToday && !landed ? 'Added to Today.' : null,
        reminder ? `I’ll remind you ${reminder.label.toLowerCase()}.` : null,
        sent ? `Sent to ${sent.label}.` : null,
    ]
        .filter(Boolean)
        .join(' ')

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                closeEvidence()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [closeEvidence])

    return (
        <div className="TodayDrawerLayer">
            <button
                type="button"
                className="TodayDrawerLayer__backdrop TodayDrawerLayer__backdrop--blur"
                aria-label="Close evidence"
                onClick={closeEvidence}
            />
            <aside
                className="TodayDrawer TodayDrawer--wide"
                role="dialog"
                aria-label={evidence.eyebrow}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ '--card-color': evidence.color } as React.CSSProperties}
            >
                <div className="TodayDrawer__head">
                    <div className="TodayDrawer__identity">
                        <span
                            className="size-2.5 rounded-sm"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ background: evidence.color, boxShadow: `0 0 0 4px ${evidence.color}24` }}
                        />
                        <span>{evidence.eyebrow}</span>
                    </div>
                    <button
                        type="button"
                        className="TodayDrawer__iconButton"
                        aria-label="Close"
                        data-attr="today-flow-drawer-close"
                        onClick={closeEvidence}
                    >
                        <IconX />
                    </button>
                </div>
                <div className="TodayDrawer__body">
                    <div className="Today__label">What I found</div>
                    <h2>{evidence.title}</h2>
                    <p>{evidence.summary}</p>
                    <div className="TodayBreakdown">
                        <div className="TodayBreakdown__head">
                            Breakdown
                            <span>{evidence.source}</span>
                        </div>
                        {evidence.steps.map((step, index) => (
                            <div key={step.label} className="TodayBreakdown__row">
                                <span>
                                    {step.label}
                                    <code>{step.value}</code>
                                </span>
                                <i>
                                    {/* eslint-disable-next-line react/forbid-dom-props */}
                                    <b style={{ width: `${step.width}%`, animationDelay: `${index * 90}ms` }} />
                                </i>
                                <small>{breakdownDelta(first, step.value, index)}</small>
                            </div>
                        ))}
                    </div>
                    <div className="TodayDrawer__section">
                        <div className="Today__label mb-2.5">What I think we can do</div>
                        {recommendationReady ? (
                            <>
                                <div className="TodayRecommendation">
                                    <span aria-hidden>↗</span>
                                    <span>{evidence.recommendation}</span>
                                </div>
                                <div className="TodayFlowActions">
                                    <button
                                        type="button"
                                        className="TodayFlowAction TodayFlowAction--primary"
                                        data-done={landed}
                                        disabled={landed}
                                        data-attr="today-flow-land"
                                        onClick={() => land(evidence.id)}
                                    >
                                        {landed ? <IconCheck /> : null}
                                        {landed ? evidence.done : evidence.action}
                                        {!landed && <IconChevronRight />}
                                    </button>
                                    <button
                                        type="button"
                                        className="TodayFlowAction TodayFlowAction--secondary"
                                        data-done={inToday}
                                        disabled={inToday}
                                        data-attr="today-flow-add-to-today"
                                        onClick={() => addToToday(evidence.id)}
                                    >
                                        {inToday ? <IconCheck /> : <IconPlus />}
                                        {inToday ? 'In Today' : 'Add to Today'}
                                    </button>
                                    <LemonMenu
                                        items={REMIND_OPTIONS.map((option) => ({
                                            label: option.detail ? `${option.label} · ${option.detail}` : option.label,
                                            onClick: () => remind(evidence.id, option.id),
                                        }))}
                                    >
                                        <button type="button" className="TodayFlowAction TodayFlowAction--secondary">
                                            <IconClock />
                                            Remind me…
                                            <IconChevronDown />
                                        </button>
                                    </LemonMenu>
                                    <LemonMenu
                                        items={SEND_OPTIONS.map((option) => ({
                                            label: option.label,
                                            tooltip: option.detail,
                                            onClick: () => send(evidence.id, option.id),
                                        }))}
                                    >
                                        <button type="button" className="TodayFlowAction TodayFlowAction--secondary">
                                            <IconSend />
                                            Send to…
                                            <IconChevronDown />
                                        </button>
                                    </LemonMenu>
                                </div>
                                <div className="TodayNext__message" role="status">
                                    {status}
                                </div>
                            </>
                        ) : (
                            <div className="TodayRecommendation TodayRecommendation--loading">
                                <span className="TodayLoadingDots" aria-hidden>
                                    <i />
                                    <i />
                                    <i />
                                </span>
                                Working out the highest-leverage next step…
                            </div>
                        )}
                    </div>
                    {(messages.length > 0 || typing) && (
                        <div className="TodayChat" aria-live="polite">
                            {messages.map((message, index) => (
                                <p key={index} data-from={message.from}>
                                    {message.text}
                                </p>
                            ))}
                            {typing && (
                                <p data-from="posthog">
                                    <span className="TodayLoadingDots" aria-label="PostHog is typing">
                                        <i />
                                        <i />
                                        <i />
                                    </span>
                                </p>
                            )}
                        </div>
                    )}
                </div>
                <form
                    className="TodayDrawer__prompt"
                    onSubmit={(event) => {
                        event.preventDefault()
                        const trimmed = chatQuestion.trim()
                        if (trimmed && !typing) {
                            askAboutEvidence(evidence.id, trimmed)
                            setChatQuestion('')
                        }
                    }}
                >
                    <input
                        value={chatQuestion}
                        placeholder="Ask about this data…"
                        aria-label="Ask about this data"
                        onChange={(event) => setChatQuestion(event.target.value)}
                    />
                    <button
                        type="submit"
                        className="TodaySend"
                        aria-label="Send"
                        disabled={!chatQuestion.trim() || typing}
                    >
                        <IconArrowRight />
                    </button>
                </form>
            </aside>
        </div>
    )
}
