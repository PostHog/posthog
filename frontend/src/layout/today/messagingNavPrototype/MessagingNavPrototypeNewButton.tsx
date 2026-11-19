// PROTOTYPE, never merged: PostHog/michaelr-context#419. One New menu for the three kinds of thing you send.
import { router } from 'kea-router'

import { IconCode, IconDecisionTree, IconPlus, IconSend } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    IconStack,
    IconStackItem,
    ItemContent,
    ItemDescription,
    ItemTitle,
} from '@posthog/quill'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

interface NewItem {
    key: string
    title: string
    description: string
    icon: JSX.Element
    color: string
    onClick: () => void
}

const NEW_ITEMS: NewItem[] = [
    {
        key: 'broadcast',
        title: 'Broadcast',
        description: 'Send one message to a group of people, now or at a set time.',
        icon: <IconSend />,
        color: 'var(--color-product-broadcasts-light)',
        onClick: () => lemonToast.info('Prototype: this opens the broadcast editor.'),
    },
    {
        key: 'transactional',
        title: 'Transactional email',
        description: 'An email your code sends with one API call.',
        icon: <IconCode />,
        color: 'var(--color-product-workflows-light)',
        onClick: () => lemonToast.info('Prototype: this opens a new transactional email.'),
    },
    {
        key: 'workflow',
        title: 'Workflow',
        description: 'A sequence of messages that an event starts. It begins with a message step.',
        icon: <IconDecisionTree />,
        color: 'var(--color-product-workflows-light)',
        onClick: () => router.actions.push('/workflows/new/workflow'),
    },
]

export function MessagingNavPrototypeNewButton({ inline = false }: { inline?: boolean }): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    inline ? (
                        <Button variant="primary" data-attr="messaging-prototype-new" />
                    ) : (
                        <Button
                            size="icon"
                            className="-me-2 text-muted-foreground"
                            aria-label="New in Email & Messaging"
                            data-attr="messaging-prototype-new-header"
                        />
                    )
                }
            >
                <IconPlus />
                {inline && 'New'}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-72">
                {NEW_ITEMS.map((item) => (
                    <DropdownMenuItem
                        key={item.key}
                        className="h-auto cursor-pointer items-start py-1.5 whitespace-normal"
                        onClick={item.onClick}
                    >
                        <IconStack className="mt-0.5 shrink-0">
                            <IconStackItem color={item.color}>{item.icon}</IconStackItem>
                        </IconStack>
                        <ItemContent variant="menuItem">
                            <ItemTitle>{item.title}</ItemTitle>
                            <ItemDescription>{item.description}</ItemDescription>
                        </ItemContent>
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

/** The pane header's New button, which takes no props like the other panes' actions. */
export function MessagingNavPrototypeHeaderNewButton(): JSX.Element {
    return <MessagingNavPrototypeNewButton />
}
