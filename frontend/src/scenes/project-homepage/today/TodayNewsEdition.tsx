import { useActions } from 'kea'

import { cn } from '@posthog/quill'

import type { NewsEditionApi, NewsOngoingStoryApi, NewsStoryApi } from 'products/today/frontend/generated/api.schemas'

import { TodayNewsBriefs } from './TodayNewsBriefs'
import { TodayNewsColumns } from './TodayNewsColumns'
import { leadHasChart, storiesUnderLead } from './todayNewsLayout'
import { TodayNewsLead } from './TodayNewsLead'
import { type TodayNewsRatedStory, todayNewsLogic } from './todayNewsLogic'
import { TodayNewsOngoing } from './TodayNewsOngoing'
import { TodayNewsSectionLabel } from './TodayNewsSectionLabel'
import { TodayNewsStory } from './TodayNewsStory'

export function TodayNewsEdition({ edition }: { edition: NewsEditionApi }): JSX.Element {
    const { diveIn } = useActions(todayNewsLogic)
    const { lead, stories, ongoing, this_week: thisWeek, briefs } = edition
    const hasOngoing = ongoing.length > 0
    const fresh = 1 + stories.length
    const underLead = storiesUnderLead(stories, leadHasChart(lead), ongoing.length, briefs.length > 0)
    const columns = stories.slice(underLead.length)
    const briefsInRail = briefs.length > 0 && hasOngoing
    const briefsInColumns = briefs.length > 0 && !briefsInRail && columns.length > 0 && columns.length < 3
    const columnCount = columns.length + (briefsInColumns ? 1 : 0)
    const rated = (
        part: TodayNewsRatedStory['part'],
        story: { id: string; product: string },
        position: number
    ): TodayNewsRatedStory => ({
        key: `${edition.id}:${part}:${story.id}`,
        id: story.id,
        part,
        product: story.product,
        position,
    })
    const storyProps = (
        part: TodayNewsRatedStory['part'],
        story: NewsStoryApi,
        position: number
    ): { story: NewsStoryApi; rated: TodayNewsRatedStory; onDiveIn: () => void } => ({
        story,
        rated: rated(part, story, position),
        onDiveIn: () => diveIn(story, position),
    })
    const ongoingPosition = (index: number): number => fresh + thisWeek.length + index
    const diveInOngoing = (item: NewsOngoingStoryApi, index: number): void =>
        diveIn({ ...item, summary: item.update, change: null }, ongoingPosition(index))

    return (
        <div className="@container flex flex-col">
            <div className={cn('grid', hasOngoing && '@3xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]')}>
                <div className="flex flex-col">
                    <div className={cn('px-4 py-6', hasOngoing && '@3xl:pe-6')}>
                        <TodayNewsLead
                            story={lead}
                            stacked={hasOngoing}
                            rated={rated('lead', lead, 0)}
                            onDiveIn={() => diveIn(lead, 0)}
                        />
                    </div>
                    {underLead.length > 0 ? (
                        <ul className="m-0 list-none p-0 [&>li]:border-t [&>li]:px-4 [&>li]:py-6 @3xl:[&>li]:pe-6">
                            {underLead.map((story, index) => (
                                <TodayNewsStory key={story.id} wide {...storyProps('story', story, index + 1)} />
                            ))}
                        </ul>
                    ) : null}
                </div>
                {hasOngoing ? (
                    <aside className="border-t px-4 py-6 @3xl:border-s @3xl:border-t-0 @3xl:ps-6">
                        <TodayNewsOngoing
                            items={ongoing}
                            rated={(item, index) => rated('ongoing', item, ongoingPosition(index))}
                            onDiveIn={diveInOngoing}
                        />
                        {briefsInRail ? (
                            <div className="mt-4 border-t pt-4">
                                <TodayNewsBriefs briefs={briefs} />
                            </div>
                        ) : null}
                    </aside>
                ) : null}
            </div>
            {columns.length > 0 ? (
                <div className="border-t">
                    <TodayNewsColumns count={columnCount}>
                        {columns.map((story, index) => (
                            <TodayNewsStory
                                key={story.id}
                                wide={index === 0 && columnCount === 2}
                                {...storyProps('story', story, underLead.length + index + 1)}
                            />
                        ))}
                        {briefsInColumns ? (
                            <li>
                                <TodayNewsBriefs briefs={briefs} />
                            </li>
                        ) : null}
                    </TodayNewsColumns>
                </div>
            ) : null}
            {thisWeek.length > 0 ? (
                <section className="border-t">
                    <div className="border-b px-4 py-3">
                        <TodayNewsSectionLabel>This week</TodayNewsSectionLabel>
                    </div>
                    <TodayNewsColumns count={thisWeek.length}>
                        {thisWeek.map((story, index) => (
                            <TodayNewsStory key={story.id} {...storyProps('this_week', story, fresh + index)} />
                        ))}
                    </TodayNewsColumns>
                </section>
            ) : null}
            {briefs.length > 0 && !briefsInRail && !briefsInColumns ? (
                <div className="border-t px-4 py-4">
                    <TodayNewsBriefs briefs={briefs} />
                </div>
            ) : null}
        </div>
    )
}
