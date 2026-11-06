import type { TodayNewsStory } from './todayNewsEdition'
import { TodayNewsKicker } from './TodayNewsKicker'

export function TodayNewsStoryRow({ story, onDiveIn }: { story: TodayNewsStory; onDiveIn: () => void }): JSX.Element {
    return (
        <li className="border-t py-4 first:border-t-0 first:pt-0 last:pb-0">
            <button
                type="button"
                onClick={onDiveIn}
                aria-label={`Dive in: ${story.title}`}
                className="group/story flex w-full cursor-pointer flex-col gap-1.5 rounded-sm text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                data-attr="today-news-dive-in"
            >
                <TodayNewsKicker story={story} />
                <span className="text-lg leading-tight font-bold tracking-tight text-pretty decoration-2 underline-offset-4 group-hover/story:underline">
                    {story.title}
                </span>
                <span className="text-sm text-pretty text-muted-foreground">{story.summary}</span>
            </button>
        </li>
    )
}
