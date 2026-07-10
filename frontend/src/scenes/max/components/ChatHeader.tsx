import { useActions, useValues } from 'kea'

import { IconOpenSidebar, IconShare } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { SceneName } from '~/layout/scenes/components/SceneTitleSection'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { PhaiViewToggle } from './PhaiViewToggle'

/* Sits above the chat area */
export function ChatHeader({
    conversationId,
    tabId,
    children,
    hideBorder,
}: {
    conversationId: string | null
    tabId?: string
    children?: React.ReactNode
    hideBorder?: boolean
}): JSX.Element {
    const { openSidePanelMax } = useActions(maxGlobalLogic)
    const { chatTitle } = useValues(maxLogic)
    const isTitleLoading = chatTitle === 'New chat'

    return (
        <div
            className={cn(
                'flex w-full gap-2 py-2 border-b border-primary items-center justify-between px-2',
                hideBorder && 'border-b-0'
            )}
        >
            <div className="flex items-center gap-2 pl-2 text-sm font-medium truncate min-w-0 flex-1">
                {children}
                {chatTitle === null ? null : isTitleLoading ? (
                    <div className="w-100">
                        <SceneName name="New chat" isLoading />
                    </div>
                ) : (
                    <SceneName name={chatTitle} />
                )}
            </div>
            <div className="flex items-center gap-2">
                <PhaiViewToggle variant="lemon" />
                {conversationId ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        sideIcon={<IconShare />}
                        onClick={() => {
                            copyToClipboard(
                                urls.absolute(urls.currentProject(urls.ai(conversationId ?? undefined))),
                                'conversation sharing link'
                            )
                        }}
                    >
                        Copy link
                    </LemonButton>
                ) : undefined}
                {tabId ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        sideIcon={<IconOpenSidebar />}
                        onClick={() => {
                            openSidePanelMax(conversationId ?? undefined)
                        }}
                    >
                        Open in context panel
                    </LemonButton>
                ) : undefined}
            </div>
        </div>
    )
}
