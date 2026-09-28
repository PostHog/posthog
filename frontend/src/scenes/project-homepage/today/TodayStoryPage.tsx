import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { TodayAskBox } from './TodayAskBox'
import { TodayEvidenceStack } from './TodayEvidenceStack'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayNextStep } from './TodayNextStep'
import { TodayStory } from './todayTypes'

export function TodayStoryHeader({ kicker, icon }: { kicker: string; icon: JSX.Element | null }): JSX.Element {
    return (
        <div className="TodayStory__kicker">
            <span className="TodayTile">{icon}</span>
            <span>{kicker}</span>
        </div>
    )
}

export function TodayStoryPage({ story }: { story: TodayStory }): JSX.Element {
    return (
        <div
            className="TodayStory Today__page"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--story-color': story.color } as React.CSSProperties}
        >
            <article>
                <TodayStoryHeader kicker={story.title} icon={<TodayIcon story={story.icon} />} />
                <h1 className="TodayStory__heading">{story.heading}</h1>
                <div className="TodayStory__body">
                    {story.paragraphs.map((paragraph, index) => (
                        <p key={index}>{paragraph}</p>
                    ))}
                </div>
            </article>
            <TodayNextStep story={story} />
            <TodayEvidenceStack story={story} />
            <TodayAskBox compact />
        </div>
    )
}

export function TodayStoryMissing(): JSX.Element {
    const { openHome } = useActions(todayLogic)
    return (
        <div className="TodayStory Today__page">
            <h1 className="TodayStory__heading">This story is no longer on your list.</h1>
            <div className="TodayStory__body">
                <p>It may have been resolved or removed. Head back to today’s briefing to see what still needs you.</p>
            </div>
            <div className="mt-6">
                <LemonButton type="primary" onClick={openHome} data-attr="today-story-missing-home">
                    Back to Home
                </LemonButton>
            </div>
        </div>
    )
}
