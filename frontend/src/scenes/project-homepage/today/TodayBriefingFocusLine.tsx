import { useActions, useValues } from 'kea'

import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { Chip, ChipClose } from '@posthog/quill'

import { todayBriefingFocusLogic } from './todayBriefingFocusLogic'
import { sourceLabel } from './todaySignalReports'

/** The topics the briefing is steered toward or away from, under the greeting. Each one can be removed in place. */
export function TodayBriefingFocusLine(): JSX.Element | null {
    const { topics } = useValues(todayBriefingFocusLogic)
    const { removeTopic } = useActions(todayBriefingFocusLogic)
    if (topics.length === 0) {
        return null
    }
    return (
        <div className="TodayHome__focus" data-attr="today-briefing-focus-line">
            <span>Your focus</span>
            {topics.map(({ topic, direction }) => {
                const label = `${direction === 'more' ? 'More' : 'Less'} ${sourceLabel(topic)}`
                return (
                    <Chip key={topic} size="xs" data-attr="today-briefing-focus-topic">
                        {direction === 'more' ? <IconThumbsUp /> : <IconThumbsDown />}
                        <span>{label}</span>
                        <ChipClose
                            aria-label={`Remove ${label}`}
                            onClick={() => removeTopic(topic)}
                            data-attr="today-briefing-focus-remove"
                        />
                    </Chip>
                )
            })}
        </div>
    )
}
