import { useMemo } from 'react'

import { IconChat } from '@posthog/icons'
import { Item, ItemContent, ItemSeparator, ItemTitle } from '@posthog/quill'

import { TodayChatActionItems } from './TodayChatActionItems'
import { TodayHoverCardFact } from './TodayHoverCardFact'
import { cardMenuParts } from './todayMenuParts'
import { TodayChatPreview } from './todayPreviewCards'
import { activityDetail } from './todayWorkItems'

const NO_SUBMENU = (): void => {}

export function TodayChatHoverCard({
    preview,
    onAction,
}: {
    preview: TodayChatPreview
    onAction: () => void
}): JSX.Element {
    const updated = activityDetail(preview.timestamp)
    const parts = useMemo(() => cardMenuParts(onAction, NO_SUBMENU), [onAction])
    return (
        <div className="flex flex-col" data-attr="today-chat-hover-card">
            <Item size="xs" className="items-start">
                <ItemContent className="min-w-0 gap-2">
                    <ItemTitle className="flex items-start gap-2 wrap-anywhere">
                        <span className="flex h-lh w-4 shrink-0 items-center justify-center text-muted-foreground">
                            <IconChat />
                        </span>
                        <span className="min-w-0 font-semibold">{preview.title}</span>
                    </ItemTitle>
                    <div className="flex flex-col gap-1 pl-6">
                        <TodayHoverCardFact label="Source">{preview.source}</TodayHoverCardFact>
                        {updated && (
                            <TodayHoverCardFact label="Updated">
                                <span title={updated.title}>{updated.text}</span>
                            </TodayHoverCardFact>
                        )}
                    </div>
                </ItemContent>
            </Item>
            <ItemSeparator className="my-0" />
            <div className="flex flex-col p-1">
                <TodayChatActionItems parts={parts} chatId={preview.chatId} dataAttrPrefix="today-chat-card" />
            </div>
        </div>
    )
}
