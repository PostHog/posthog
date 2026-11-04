import { useActions } from 'kea'

import { IconHide, IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import type { HighlightItemApi } from 'products/today/frontend/generated/api.schemas'

import { TodayFeedCard, type TodayFeedCardTracking } from './TodayFeedCard'
import { highlightActionLabel, highlightSourceLabel, splitHighlightTitle } from './todayFeedText'
import { todayHighlightsLogic } from './todayHighlightsLogic'
import { todayLogic } from './todayLogic'
import { priorityTone } from './todayPriority'
import { highlightIcon } from './todayRowIcons'

export function TodayFeedHighlightCard({
    item,
    position,
    done,
    tracking,
}: {
    item: HighlightItemApi
    position: number
    done: boolean
    tracking: TodayFeedCardTracking
}): JSX.Element {
    const { highlightOpened, hideHighlight, unhideHighlight } = useActions(todayHighlightsLogic)
    const { askAi } = useActions(todayLogic)
    const { title, quote, period } = splitHighlightTitle(item.title)
    return (
        <TodayFeedCard
            icon={highlightIcon(item)}
            source={highlightSourceLabel(item)}
            title={title}
            tone={priorityTone(item.priority)}
            priority={item.priority}
            meta={[item.label === 'opportunity' ? 'Opportunity' : null, period].filter(Boolean).join(' · ')}
            quote={quote}
            lead={item.detail}
            series={item.series}
            secondaryActions={
                done ? (
                    <Button
                        variant="link-muted"
                        size="sm"
                        onClick={() => unhideHighlight(item, position)}
                        data-attr="today-feed-highlight-unhide"
                    >
                        Undo
                    </Button>
                ) : (
                    <Button
                        variant="link-muted"
                        size="icon-sm"
                        aria-label="Hide for today"
                        tooltip="Hide for today"
                        onClick={() => hideHighlight(item, position)}
                        data-attr="today-feed-highlight-hide"
                    >
                        <IconHide />
                    </Button>
                )
            }
            open={
                item.url
                    ? {
                          to: item.url,
                          label: highlightActionLabel(item.source),
                          onOpen: () => highlightOpened(item, position),
                      }
                    : undefined
            }
            fallbackAction={
                <Button
                    variant="link-muted"
                    size="sm"
                    className="TodayFeedCard__primary"
                    onClick={() => askAi(`Why did this happen: ${item.title}?`, 'feed')}
                    data-attr="today-feed-highlight-ask"
                >
                    <IconSparkles />
                    Ask PostHog AI why
                </Button>
            }
            done={done}
            tracking={tracking}
            dataAttr="today-feed-highlight"
        />
    )
}
