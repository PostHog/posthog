import { useActions } from 'kea'

import { IconSidePanel } from '@posthog/icons'

import { IconUndockPanel } from 'lib/lemon-ui/icons'

import { todayAiChatLogic } from './todayAiChatLogic'
import type { TodayMenuParts } from './todayMenuParts'
import type { TodayPanelChatTask } from './todayPanelChat'

interface TodayPanelMoveMenuItemsProps {
    parts: TodayMenuParts
    /** The task whose run the panel takes over. Without one, the panel opens on a new chat. */
    chat: TodayPanelChatTask | null
    dataAttrPrefix: string
}

export function TodayPanelMoveMenuItems({ parts, chat, dataAttrPrefix }: TodayPanelMoveMenuItemsProps): JSX.Element {
    const { moveChatToPanel } = useActions(todayAiChatLogic)

    return (
        <>
            <parts.Item
                onClick={() => moveChatToPanel('floating', chat)}
                dataAttr={`${dataAttrPrefix}-move-to-floating-panel`}
            >
                <IconUndockPanel />
                Open in floating panel
            </parts.Item>
            <parts.Item
                onClick={() => moveChatToPanel('docked', chat)}
                dataAttr={`${dataAttrPrefix}-move-to-side-panel`}
            >
                <IconSidePanel />
                Dock to the right
            </parts.Item>
        </>
    )
}
