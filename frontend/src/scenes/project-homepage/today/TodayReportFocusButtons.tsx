import { useActions, useValues } from 'kea'

import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { todayBriefingFocusLogic } from './todayBriefingFocusLogic'

/** "More like this" and "Less like this" on a report's hover card. A second press takes the topic out of the focus. */
export function TodayReportFocusButtons({ topic, label }: { topic: string; label: string }): JSX.Element {
    const { directions } = useValues(todayBriefingFocusLogic)
    const { steerTopic } = useActions(todayBriefingFocusLogic)
    return (
        <div className="flex flex-wrap justify-between gap-1.5 px-3 py-2">
            <Button
                variant={directions[topic] === 'more' ? 'outline' : 'ghost'}
                size="xs"
                aria-pressed={directions[topic] === 'more'}
                title={`Show more ${label} reports in your briefing`}
                onClick={() => steerTopic(topic, 'more')}
                data-attr="today-report-hover-card-focus-more"
            >
                <IconThumbsUp />
                More like this
            </Button>
            <Button
                variant={directions[topic] === 'less' ? 'outline' : 'ghost'}
                size="xs"
                aria-pressed={directions[topic] === 'less'}
                title={`Show fewer ${label} reports in your briefing`}
                onClick={() => steerTopic(topic, 'less')}
                data-attr="today-report-hover-card-focus-less"
            >
                <IconThumbsDown />
                Less like this
            </Button>
        </div>
    )
}
