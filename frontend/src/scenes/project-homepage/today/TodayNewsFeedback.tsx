import { useActions, useValues } from 'kea'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { type TodayNewsRatedStory, todayNewsLogic } from './todayNewsLogic'

export function TodayNewsFeedback({ story }: { story: TodayNewsRatedStory }): JSX.Element {
    const { storyRatings } = useValues(todayNewsLogic)
    const { rateStory } = useActions(todayNewsLogic)
    const rating = storyRatings[story.key]
    return (
        <span className="flex items-center gap-0.5">
            <Button
                size="icon-xs"
                variant="default"
                tooltip={rating === 'up' ? 'Remove thumbs up' : 'Yes, this was useful'}
                aria-label="This story was useful"
                aria-pressed={rating === 'up'}
                data-attr="today-news-feedback-up"
                onClick={() => rateStory(story, 'up')}
            >
                {rating === 'up' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
            </Button>
            <Button
                size="icon-xs"
                variant="default"
                tooltip={rating === 'down' ? 'Remove thumbs down' : "No, this wasn't useful"}
                aria-label="This story was not useful"
                aria-pressed={rating === 'down'}
                data-attr="today-news-feedback-down"
                onClick={() => rateStory(story, 'down')}
            >
                {rating === 'down' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
            </Button>
        </span>
    )
}
