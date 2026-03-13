import { useActions } from 'kea'
import { combineUrl } from 'kea-router'

import { IconEllipsis, IconMessage, IconOpenSidebar, IconShare } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
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
        <>
            {showIcon && (
                <IconMessage className="size-4 text-secondary opacity-50 group-hover:opacity-100 transition-all duration-50" />
            )}
            <span className="flex-1 line-clamp-1 text-primary">{displayTitle}</span>
            {status === ConversationStatus.InProgress && <Spinner className="h-3 w-3" />}
            <span
                className={cn(
                    'opacity-30 text-xs pr-1.5 transition-opacity duration-100',
                    'group-hover:opacity-0 group-has-[[data-state=open]]:opacity-0'
                )}
            >
                {formatConversationDate(updatedAt)}
            </span>
        </>
    )
}

function Trigger(): JSX.Element {
    return (
        <DropdownMenuTrigger asChild>
            <ButtonPrimitive
                iconOnly
                className="
                    absolute right-0
                    translate-x-full opacity-0
                    group-hover:translate-x-0 group-hover:opacity-100
                    data-[state=open]:translate-x-0
                    data-[state=open]:opacity-100
                    transition-[opacity] duration-100 ease-initial
                "
            >
                <IconEllipsis className="text-tertiary size-3 group-hover:text-primary z-10" />
            </ButtonPrimitive>
        </DropdownMenuTrigger>
    )
}

function Root({ children }: { children: React.ReactNode }): JSX.Element {
    return <DropdownMenu>{children}</DropdownMenu>
}

function Group({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <ButtonGroupPrimitive fullWidth className="group">
            {children}
        </ButtonGroupPrimitive>
    )
}

function Actions({ conversationId }: { conversationId: string }): JSX.Element {
    const { openSidePanelMax } = useActions(maxGlobalLogic)

    return (
        <DropdownMenuContent align="end" loop className="max-w-[250px]">
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
        </DropdownMenuContent>
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
        <Root>
            <Group>
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
                <Trigger />
            </Group>
            <Actions conversationId={conversationId} />
        </Root>
    )
}

export const AiChatListItem = Object.assign(AiChatListItemRoot, {
    Root,
    Group,
    Content,
    Trigger,
    Actions,
    ContextMenuAction,
    getHref,
    getShareLink,
})
