import { useActions } from 'kea'
import { combineUrl } from 'kea-router'

import { IconMessage, IconOpenSidebar, IconShare } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { LinkListItem } from 'lib/ui/LinkListItem/LinkListItem'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { BrowserLikeMenuItems } from '~/layout/panel-layout/ProjectTree/menus/BrowserLikeMenuItems'
import { ConversationStatus } from '~/types'

import { maxGlobalLogic } from '../../maxGlobalLogic'
import { formatConversationDate } from '../../utils'

function getHref(conversationId: string): string {
    return combineUrl(urls.ai(conversationId), { from: 'history' }).url
}

function getShareLink(conversationId: string): string {
    return urls.absolute(urls.currentProject(urls.ai(conversationId)))
}

function ContextMenuAction({ conversationId }: { conversationId: string }): JSX.Element {
    const { openSidePanelMax } = useActions(maxGlobalLogic)

    return (
        <>
            <ContextMenuItem asChild>
                <ButtonPrimitive
                    menuItem
                    onClick={() => copyToClipboard(getShareLink(conversationId), 'conversation sharing link')}
                >
                    <IconShare className="size-4 text-tertiary" />
                    Copy link to chat
                </ButtonPrimitive>
            </ContextMenuItem>
            <ContextMenuItem asChild>
                <ButtonPrimitive
                    menuItem
                    onClick={() => {
                        openSidePanelMax(conversationId ?? undefined)
                    }}
                >
                    <IconOpenSidebar className="size-4 text-tertiary" />
                    Open in context panel
                </ButtonPrimitive>
            </ContextMenuItem>
        </>
    )
}

function Content({
    title,
    status,
    updatedAt,
    showIcon,
}: {
    title: string | null
    status: ConversationStatus
    updatedAt: string | null
    showIcon?: boolean
}): JSX.Element {
    const displayTitle = title || 'Untitled conversation'
    return (
        <LinkListItem.Content
            icon={showIcon ? <IconMessage /> : undefined}
            title={displayTitle}
            isLoading={status === ConversationStatus.InProgress}
            meta={formatConversationDate(updatedAt)}
        />
    )
}

function Actions({ conversationId }: { conversationId: string }): JSX.Element {
    const { openSidePanelMax } = useActions(maxGlobalLogic)

    return (
        <LinkListItem.Actions>
            <DropdownMenuGroup>
                <BrowserLikeMenuItems
                    MenuItem={DropdownMenuItem}
                    href={getShareLink(conversationId)}
                    onClick={() => copyToClipboard(getShareLink(conversationId), 'conversation sharing link')}
                />
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                    <ButtonPrimitive
                        menuItem
                        onClick={() => copyToClipboard(getShareLink(conversationId), 'conversation sharing link')}
                    >
                        <IconShare className="size-4 text-tertiary" />
                        Copy link to chat
                    </ButtonPrimitive>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                    <ButtonPrimitive
                        menuItem
                        onClick={() => {
                            openSidePanelMax(conversationId ?? undefined)
                        }}
                    >
                        <IconOpenSidebar className="size-4 text-tertiary" />
                        Open in context panel
                    </ButtonPrimitive>
                </DropdownMenuItem>
            </DropdownMenuGroup>
        </LinkListItem.Actions>
    )
}

interface AiChatListItemProps {
    conversationId: string
    title: string | null
    status: ConversationStatus
    updatedAt: string | null
    isActive?: boolean
    onClick?: (e: React.MouseEvent) => void
    compact?: boolean
    showIcon?: boolean
}

function AiChatListItemRoot({
    conversationId,
    title,
    status,
    updatedAt,
    isActive,
    onClick,
    compact,
}: AiChatListItemProps): JSX.Element {
    const displayTitle = title || 'Untitled conversation'
    const href = getHref(conversationId)

    if (compact) {
        return (
            <Link
                to={href}
                onClick={onClick}
                buttonProps={{
                    active: isActive,
                    menuItem: true,
                }}
                tooltip={displayTitle}
                tooltipPlacement="right"
            >
                <span className="flex-1 line-clamp-1 text-primary text-xs">{displayTitle}</span>
                {status === ConversationStatus.InProgress && <Spinner className="h-3 w-3" />}
            </Link>
        )
    }

    return (
        <LinkListItem.Root>
            <LinkListItem.Group>
                <Link
                    to={href}
                    onClick={onClick}
                    buttonProps={{
                        active: isActive,
                        fullWidth: true,
                        className: 'pr-0 group',
                    }}
                    tooltip={displayTitle}
                    tooltipPlacement="right"
                    extraContextMenuItems={<ContextMenuAction conversationId={conversationId} />}
                >
                    <Content title={title} status={status} updatedAt={updatedAt} showIcon />
                </Link>
                <LinkListItem.Trigger />
            </LinkListItem.Group>
            <Actions conversationId={conversationId} />
        </LinkListItem.Root>
    )
}

export const AiChatListItem = Object.assign(AiChatListItemRoot, {
    Root: LinkListItem.Root,
    Group: LinkListItem.Group,
    Content,
    Trigger: LinkListItem.Trigger,
    Actions,
    ContextMenuAction,
    getHref,
    getShareLink,
})
