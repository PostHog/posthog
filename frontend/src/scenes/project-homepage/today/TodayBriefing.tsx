import { useActions, useValues } from 'kea'

import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { TodayAskBox } from './TodayAskBox'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'
import { TodayBriefingSegment } from './todayTypes'

const DATE_FORMAT = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: '2-digit', month: 'short' })
const TIME_FORMAT = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

function TodayMetaLine(): JSX.Element {
    const { now, currentTeam, usingSampleStories } = useValues(todayLogic)
    const date = new Date(now)
    return (
        <div className="TodayHome__meta">
            <span>{`${currentTeam?.name ?? 'Your project'} · ${DATE_FORMAT.format(date)} · `}</span>
            <time translate="no">{TIME_FORMAT.format(date)}</time>
            {usingSampleStories && <span className="TodayHome__sample">Sample stories</span>}
        </div>
    )
}

function BriefingSegment({ segment }: { segment: TodayBriefingSegment }): JSX.Element {
    const { hoveredStoryId } = useValues(todayLogic)
    const { openStory, setHoveredStoryId } = useActions(todayLogic)
    const storyId = segment.link
    if (!storyId) {
        return <span>{segment.text}</span>
    }
    const link = (
        <button
            type="button"
            className="TodayStoryLink"
            data-active={hoveredStoryId === storyId}
            onClick={() => openStory(storyId)}
            onMouseEnter={() => setHoveredStoryId(storyId)}
            onMouseLeave={() => setHoveredStoryId(null)}
            onFocus={() => setHoveredStoryId(storyId)}
            onBlur={() => setHoveredStoryId(null)}
        >
            {segment.text}
        </button>
    )
    return segment.highlight ? <span className="TodayHome__highlight">{link}</span> : link
}

export function TodayBriefing(): JSX.Element {
    const { greeting, storySummary, stories, briefing, hoveredStoryId, storiesReady } = useValues(todayLogic)
    const { openStory, setHoveredStoryId } = useActions(todayLogic)
    const { askSidePanelMax } = useActions(maxGlobalLogic)
    const chips = stories.filter((story) => !story.secondary).slice(0, 6)

    return (
        <div className="TodayHome Today__page">
            <TodayMetaLine />
            <section className="TodayHome__intro" aria-label="Daily brief">
                <div className="TodayHome__greeting">{greeting}</div>
                {storiesReady ? (
                    <>
                        <p className="TodayHome__count">
                            <span>{storySummary}</span>
                            {chips.length > 0 && (
                                <span className="TodayChipStack">
                                    {chips.map((story, index) => (
                                        <button
                                            key={story.id}
                                            type="button"
                                            className="TodayChipStack__chip"
                                            aria-label={`Open ${story.title}`}
                                            data-active={hoveredStoryId === story.id}
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={
                                                {
                                                    '--index': index,
                                                    '--tilt': index % 2 === 0 ? '-3deg' : '3deg',
                                                    '--story-color': story.color,
                                                } as React.CSSProperties
                                            }
                                            onClick={() => openStory(story.id)}
                                            onMouseEnter={() => setHoveredStoryId(story.id)}
                                            onMouseLeave={() => setHoveredStoryId(null)}
                                            onFocus={() => setHoveredStoryId(story.id)}
                                            onBlur={() => setHoveredStoryId(null)}
                                        >
                                            <TodayIcon story={story.icon} />
                                        </button>
                                    ))}
                                </span>
                            )}
                        </p>
                        {briefing.map((paragraph, index) => (
                            <p key={index}>
                                {paragraph.map((segment, segmentIndex) => (
                                    <BriefingSegment key={segmentIndex} segment={segment} />
                                ))}
                            </p>
                        ))}
                        <p className="TodayHome__foot">
                            <span>Or </span>
                            <button
                                type="button"
                                data-attr="today-ask-about-edition"
                                onClick={() => askSidePanelMax('Walk me through what changed in my product today.')}
                            >
                                ask PostHog AI to walk you through it
                            </button>
                            <span>.</span>
                        </p>
                    </>
                ) : (
                    <p>Reading what changed in your project…</p>
                )}
            </section>
            <TodayAskBox />
        </div>
    )
}
