import { useActions } from 'kea'

import { IconCopy, IconExternal } from '@posthog/icons'

import { todayChatMenuLogic } from './todayChatMenuLogic'
import { TodayMenuParts } from './todayMenuParts'

interface TodayChatActionItemsProps {
    parts: TodayMenuParts
    chatId: string
    dataAttrPrefix: string
}

export function TodayChatActionItems({
    parts: { Item },
    chatId,
    dataAttrPrefix,
}: TodayChatActionItemsProps): JSX.Element {
    const { openChatInNewTab, copyChatLink } = useActions(todayChatMenuLogic)
    const attr = (name: string): string => `${dataAttrPrefix}-${name}`

    return (
        <>
            <Item onClick={() => openChatInNewTab(chatId)} dataAttr={attr('open-new-tab')}>
                <IconExternal />
                Open in new tab
            </Item>
            <Item onClick={() => copyChatLink(chatId)} dataAttr={attr('copy-link')}>
                <IconCopy />
                Copy link
            </Item>
        </>
    )
}
