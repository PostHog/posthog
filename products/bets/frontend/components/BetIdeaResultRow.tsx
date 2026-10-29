import type { CSSProperties, ReactNode } from 'react'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { BetsResultIdeaApi } from '../generated/api.schemas'
import { money } from '../lib/format'
import { type EffectAxis, OUTCOMES, effectX, pullRequestNumber } from '../lib/results'
import { BetEffectInterval } from './BetEffectInterval'
import { BetIdeaNumber } from './BetIdeaNumber'
import { BetWorkStatusIcon } from './BetWorkStatusIcon'

function emptyEffect(idea: BetsResultIdeaApi): string {
    if (idea.outcome === 'broken') {
        return 'No reliable result'
    }
    return idea.pr_url ? 'Not measured' : 'Not built'
}

function pullRequest(idea: BetsResultIdeaApi): ReactNode {
    const pr = pullRequestNumber(idea.pr_url)
    if (!pr) {
        return idea.shipped ? 'shipped' : null
    }
    return (
        <LinkPrimitive to={idea.pr_url} target="_blank" className="BetsResults__link">
            {idea.shipped ? `shipped in PR ${pr}` : `PR ${pr}`}
        </LinkPrimitive>
    )
}

export function BetIdeaResultRow({
    idea,
    position,
    axis,
    first,
}: {
    idea: BetsResultIdeaApi
    position: number
    axis: EffectAxis | null
    first: boolean
}): JSX.Element {
    const outcome = OUTCOMES[idea.outcome]
    const people =
        idea.people !== null
            ? `${idea.people.toLocaleString('en-US')} people${idea.weak_evidence ? ', small sample' : ''}`
            : ''
    const facts: ReactNode[] = [people, money(idea.spent_cents), pullRequest(idea)].filter(Boolean)
    const notes = [idea.learning, idea.dismissed_reason].filter(Boolean)
    return (
        <li className="BetsResults__idea" data-attr="bets-results-idea">
            <span className="BetsResults__number">
                <BetIdeaNumber number={idea.number ?? position} won={idea.outcome === 'won'} />
            </span>
            <div className="min-w-0">
                <span className="TodayRow__title">{idea.title}</span>
                <p className="BetsResults__meta">
                    <span className="BetsResults__outcome">
                        <BetWorkStatusIcon status={{ label: outcome.label, mark: outcome.mark }} />
                        {outcome.label}
                    </span>
                    {facts.length > 0 && (
                        <span>
                            {facts.map((fact, index) => (
                                <span key={index}>
                                    {index > 0 && ', '}
                                    {fact}
                                </span>
                            ))}
                        </span>
                    )}
                </p>
                {notes.map((note) => (
                    <p key={note} className="BetsResults__note">
                        {note}
                    </p>
                ))}
            </div>
            {axis && (
                <div
                    className="BetsResults__plot"
                    data-first={first || undefined}
                    style={{ '--interval-zero': String(effectX(0, axis, 1)) } as CSSProperties}
                >
                    <span className="BetsResults__zero" />
                    {idea.effect ? (
                        <BetEffectInterval
                            lower={idea.effect[0]}
                            upper={idea.effect[1]}
                            axis={axis}
                            outcome={idea.outcome}
                        />
                    ) : (
                        <span className="BetsResults__noEffect">{emptyEffect(idea)}</span>
                    )}
                </div>
            )}
        </li>
    )
}
