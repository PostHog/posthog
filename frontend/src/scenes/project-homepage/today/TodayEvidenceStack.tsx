import { useActions } from 'kea'

import { todayDrawersLogic } from './todayDrawersLogic'
import { TodayIcon } from './TodayIcon'
import { countWord } from './todayLogic'
import { TodayStory } from './todayTypes'

export function TodayEvidenceStack({ story }: { story: TodayStory }): JSX.Element | null {
    const { openEvidence } = useActions(todayDrawersLogic)
    if (!story.evidence.length) {
        return null
    }
    return (
        <section className="TodayEvidence">
            <div className="Today__label">{`Evidence · built from ${countWord(story.evidence.length).toLowerCase()} ${story.evidence.length === 1 ? 'product' : 'products'}`}</div>
            <div className="TodayEvidence__stack">
                {story.evidence.map((evidence, index) => (
                    <button
                        key={`${evidence.product}-${index}`}
                        type="button"
                        className="TodayEvidenceCard"
                        aria-label={`Open ${evidence.product}: ${evidence.value}`}
                        data-attr="today-evidence-card"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ '--index': index, '--evidence-color': evidence.color } as React.CSSProperties}
                        onClick={() => openEvidence(story, index)}
                    >
                        <span className="TodayEvidenceCard__top">
                            <span className="TodayTile">
                                <TodayIcon evidence={evidence.kind} />
                            </span>
                            <span>{evidence.product}</span>
                        </span>
                        <strong>{evidence.value}</strong>
                        <p>{evidence.detail}</p>
                    </button>
                ))}
            </div>
        </section>
    )
}
