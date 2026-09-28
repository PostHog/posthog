import { useActions, useValues } from 'kea'

import {
    IconCalendar,
    IconCheck,
    IconChevronDown,
    IconChevronRight,
    IconGitBranch,
    IconRocket,
    IconShieldExclamation,
    IconSparkles,
} from '@posthog/icons'
import { LemonDialog, LemonMenu } from '@posthog/lemon-ui'

import { AGENT_OPTIONS, FOLLOW_UP_OPTIONS } from './todayFixtures'
import { TodayIcon } from './TodayIcon'
import { actionRun, todayLogic } from './todayLogic'
import { TodayStory } from './todayTypes'

function TodaySpinnerGlyph(): JSX.Element {
    return (
        <svg className="TodaySpinner" viewBox="0 0 18 18" fill="none" aria-hidden>
            <circle cx="9" cy="9" r="7" stroke="#8d8d88" strokeWidth="2" strokeDasharray="28 16" />
        </svg>
    )
}

export function TodayNextStep({ story }: { story: TodayStory }): JSX.Element {
    const { actionStates, actionMessage, followUpTimes } = useValues(todayLogic)
    const { runStoryAction, sendToAgent, openFollowUp } = useActions(todayLogic)
    const { action } = story
    const state = actionStates[story.id] ?? (story.completed ? 'complete' : 'idle')
    const run = actionRun(story)
    const waiting = !!action.waitingOn && state === 'idle'
    const followUpTime = followUpTimes[story.id] ?? 'tomorrow'
    const followUpChip = FOLLOW_UP_OPTIONS.find((option) => option.id === followUpTime)?.chip

    const label =
        state === 'loading'
            ? (run?.loading ?? 'Working…')
            : state === 'complete'
              ? (action.done ?? 'Completed')
              : action.primary
    const icon =
        state === 'loading' ? (
            <TodaySpinnerGlyph />
        ) : action.pr ? (
            <IconGitBranch />
        ) : state === 'complete' ? (
            <IconCheck />
        ) : action.icon === 'ship' ? (
            <IconRocket />
        ) : (
            <TodayIcon story={story.icon} />
        )
    const signal =
        state === 'complete' && run ? { text: action.pr ? `PR ${action.pr} merged` : run.live, tone: 'success' } : null

    const onPrimary = (): void => {
        if (action.advisory && state === 'idle') {
            LemonDialog.open({
                title: `${action.primary} without testing?`,
                description: `${action.advisory.from} ${action.advisory.text}`,
                primaryButton: {
                    children: 'Merge anyway',
                    onClick: () => runStoryAction(story.id),
                    'data-attr': 'today-advisory-confirm',
                },
                secondaryButton: { children: 'Cancel' },
            })
            return
        }
        runStoryAction(story.id)
    }

    return (
        <section
            className="TodayNext"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--story-color': story.color } as React.CSSProperties}
        >
            <div className="Today__label">Recommended next step</div>
            <div className="TodayNext__row">
                <button
                    type="button"
                    className="TodayPrimary"
                    data-state={state}
                    data-waiting={waiting}
                    data-merge={!!action.pr}
                    disabled={waiting || state !== 'idle'}
                    aria-busy={state === 'loading'}
                    data-attr="today-primary-action"
                    onClick={onPrimary}
                >
                    <span className="TodayPrimary__tile">
                        {icon}
                        {action.advisory && state === 'idle' && <span className="TodayPrimary__caution">!</span>}
                    </span>
                    <span>{label}</span>
                    {state === 'idle' && !waiting && <IconChevronRight className="TodayPrimary__chevron" />}
                </button>
                <span className="TodaySignal" data-tone={signal?.tone ?? action.tone}>
                    {signal?.text ?? action.status}
                </span>
            </div>
            {waiting && (
                <div className="TodayNext__waiting">
                    <TodaySpinnerGlyph />
                    <span>{action.waitingOn}</span>
                </div>
            )}
            {action.advisory && state !== 'complete' && (
                <p className="TodayNext__advisory">
                    <IconShieldExclamation />
                    <span>
                        <strong>{action.advisory.from}</strong> {action.advisory.text}
                    </span>
                </p>
            )}
            <div className="TodayNext__secondary">
                {state === 'complete' && action.followUp && (
                    <button
                        type="button"
                        className="TodaySecondary"
                        data-attr="today-follow-up"
                        onClick={() => openFollowUp(story.id)}
                    >
                        <IconCalendar />
                        <span>{followUpTime === 'cancelled' ? 'Schedule a follow-up' : 'Follow up scheduled'}</span>
                        {followUpTime !== 'cancelled' && followUpChip && <small>{followUpChip}</small>}
                        <IconChevronRight />
                    </button>
                )}
                <LemonMenu
                    items={AGENT_OPTIONS.map((agent) => ({
                        label: (
                            <div className="flex flex-col">
                                <span className="font-semibold">{agent.name}</span>
                                <span className="text-xs text-secondary">{agent.detail}</span>
                            </div>
                        ),
                        onClick: () => sendToAgent(story.id, agent.id),
                        'data-attr': `today-send-to-${agent.id}`,
                    }))}
                >
                    <button type="button" className="TodaySecondary" data-attr="today-send-to-agent">
                        <IconSparkles />
                        <span>Send to agent…</span>
                        <IconChevronDown />
                    </button>
                </LemonMenu>
            </div>
            <div className="TodayNext__message" role="status">
                {actionMessage}
            </div>
        </section>
    )
}
