import { useActions } from 'kea'

import { IconHide } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { HighlightItemApi } from 'products/today/frontend/generated/api.schemas'

import { todayHighlightsLogic } from './todayHighlightsLogic'
import { priorityTone } from './todayPriority'
import { TodayRow } from './TodayRow'
import { highlightIcon } from './todayRowIcons'

export function TodayHighlightRow({
    item,
    position,
    done,
}: {
    item: HighlightItemApi
    position: number
    done: boolean
}): JSX.Element {
    const { highlightOpened, hideHighlight, unhideHighlight } = useActions(todayHighlightsLogic)
    return (
        <TodayRow
            tone={priorityTone(item.priority)}
            icon={highlightIcon(item)}
            title={item.title}
            label={item.priority}
            facts={item.detail.split(' · ')}
            to={item.url ?? undefined}
            onOpen={() => highlightOpened(item, position)}
            actions={
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                variant="link-muted"
                                size="icon-sm"
                                aria-label="Hide for today"
                                onClick={() => hideHighlight(item, position)}
                                data-attr="today-highlight-hide"
                            />
                        }
                    >
                        <IconHide className="size-3.5" />
                    </TooltipTrigger>
                    <TooltipContent side="bottom">Hide for today</TooltipContent>
                </Tooltip>
            }
            doneActions={
                <Button
                    variant="link-muted"
                    size="sm"
                    onClick={() => unhideHighlight(item, position)}
                    data-attr="today-highlight-unhide"
                >
                    Undo
                </Button>
            }
            done={done}
            dataAttr="today-highlight"
        />
    )
}
