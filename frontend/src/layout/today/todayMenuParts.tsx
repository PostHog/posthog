import { ReactNode } from 'react'

import { IconChevronRight } from '@posthog/icons'
import {
    Button,
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuShortcut,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuShortcut,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    ItemMenuItem,
    ItemSeparator,
    cn,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { useTodaySheetMenu } from './todaySheetMenuContext'
import { TodaySheetSub } from './TodaySheetSub'

export interface TodayMenuItemProps {
    children: ReactNode
    dataAttr: string
    onClick?: () => void
    /** Navigates instead of acting. */
    to?: string
    disabled?: boolean
    variant?: 'default' | 'destructive'
}

export interface TodayMenuSubProps {
    label: ReactNode
    title: string
    dataAttr: string
    children: ReactNode
}

/**
 * What a row's action list draws with. Each kind of row writes its actions once against these parts,
 * like PostHog Desktop, so its hover card and its menus can't drift apart.
 */
export interface TodayMenuParts {
    Item: (props: TodayMenuItemProps) => JSX.Element
    Separator: () => JSX.Element | null
    Shortcut: (props: { children: ReactNode }) => JSX.Element
    Sub: (props: TodayMenuSubProps) => JSX.Element
}

const SUB_CONTENT_CLASS = 'w-64 [&>div]:max-h-[min(20rem,var(--available-height))]'

export const DROPDOWN_PARTS: TodayMenuParts = {
    Item: ({ children, dataAttr, onClick, to, disabled, variant }) => (
        <DropdownMenuItem
            onClick={onClick}
            disabled={disabled}
            variant={variant}
            // quill draws the item as a row button by default, so a link keeps that look by rendering through one.
            {...(to ? { render: <Button variant={variant} size="row" left render={<LinkPrimitive to={to} />} /> } : {})}
            data-attr={dataAttr}
        >
            {children}
        </DropdownMenuItem>
    ),
    Separator: () => <DropdownMenuSeparator />,
    Shortcut: ({ children }) => <DropdownMenuShortcut>{children}</DropdownMenuShortcut>,
    Sub: ({ label, dataAttr, children }) => (
        <DropdownMenuSub>
            <DropdownMenuSubTrigger data-attr={dataAttr}>{label}</DropdownMenuSubTrigger>
            <DropdownMenuSubContent className={SUB_CONTENT_CLASS}>{children}</DropdownMenuSubContent>
        </DropdownMenuSub>
    ),
}

export const CONTEXT_PARTS: TodayMenuParts = {
    Item: ({ children, dataAttr, onClick, to, disabled, variant }) => (
        <ContextMenuItem
            onClick={onClick}
            disabled={disabled}
            variant={variant}
            {...(to ? { render: <Button variant={variant} size="row" left render={<LinkPrimitive to={to} />} /> } : {})}
            data-attr={dataAttr}
        >
            {children}
        </ContextMenuItem>
    ),
    Separator: () => <ContextMenuSeparator />,
    Shortcut: ({ children }) => <ContextMenuShortcut>{children}</ContextMenuShortcut>,
    Sub: ({ label, dataAttr, children }) => (
        <ContextMenuSub>
            <ContextMenuSubTrigger data-attr={dataAttr}>{label}</ContextMenuSubTrigger>
            <ContextMenuSubContent className={SUB_CONTENT_CLASS}>{children}</ContextMenuSubContent>
        </ContextMenuSub>
    ),
}

function SheetItem({ children, dataAttr, onClick, to, disabled, variant }: TodayMenuItemProps): JSX.Element {
    const sheet = useTodaySheetMenu()
    return (
        <ItemMenuItem
            className={cn(
                'no-underline',
                variant === 'destructive' ? 'text-destructive-foreground' : 'text-foreground'
            )}
            disabled={disabled}
            onClick={() => {
                onClick?.()
                sheet?.close()
            }}
            {...(to ? { render: <LinkPrimitive to={to} /> } : {})}
            data-attr={dataAttr}
        >
            {children}
        </ItemMenuItem>
    )
}

export const SHEET_PARTS: TodayMenuParts = {
    Item: SheetItem,
    Separator: () => <ItemSeparator className="my-1" />,
    Shortcut: () => <></>,
    Sub: ({ label, title, dataAttr, children }) => (
        <TodaySheetSub label={label} title={title} dataAttr={dataAttr}>
            {children}
        </TodaySheetSub>
    ),
}

/**
 * The parts for a hover card's action list. The card is not a menu, so its rows are plain buttons.
 * `onAction` closes the card after a choice. `onSubmenuOpenChange` reports "File to…", whose menu opens
 * outside the card, so the card stays open while the pointer is in it. Desktop drops the separators here.
 */
export function cardMenuParts(onAction: () => void, onSubmenuOpenChange: (open: boolean) => void): TodayMenuParts {
    return {
        Item: ({ children, dataAttr, onClick, to, disabled, variant }) => (
            <Button
                left
                className="w-full"
                variant={variant}
                disabled={disabled}
                onClick={() => {
                    onClick?.()
                    onAction()
                }}
                {...(to ? { render: <LinkPrimitive to={to} /> } : {})}
                data-attr={dataAttr}
            >
                {children}
            </Button>
        ),
        Separator: () => null,
        Shortcut: ({ children }) => <DropdownMenuShortcut>{children}</DropdownMenuShortcut>,
        Sub: ({ label, dataAttr, children }) => (
            <DropdownMenu
                onOpenChange={(open, details) => {
                    onSubmenuOpenChange(open)
                    if (!open && details.reason === 'item-press') {
                        onAction()
                    }
                }}
            >
                <DropdownMenuTrigger
                    openOnHover
                    delay={150}
                    closeDelay={100}
                    render={<Button left className="w-full" data-attr={dataAttr} />}
                >
                    <span className="flex flex-1 items-center gap-2">{label}</span>
                    <IconChevronRight />
                </DropdownMenuTrigger>
                <DropdownMenuContent side="right" align="start" className={SUB_CONTENT_CLASS}>
                    {children}
                </DropdownMenuContent>
            </DropdownMenu>
        ),
    }
}
