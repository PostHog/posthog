import { useEffect } from 'react'

import { IconSend } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItem, Link } from '@posthog/lemon-ui'

import type { TicketChannel, TicketStatus } from '../../types'
import { getReplyDestination } from '../Channels/ChannelsTag'
import { ReplyIcon } from '../ReplyIcon/ReplyIcon'

const DIGITS = ['1', '2', '3', '4', '5', '6', '7', '8', '9'] as const

export function SendMenu({
    visible,
    onVisibilityChange,
    onSend,
    onCancel,
    composerRef,
    verb,
    isPrivate,
    channel,
    audience,
    statusLabel,
    statusOptions = [],
    disabledReason,
    loading,
    children,
}: {
    visible: boolean
    onVisibilityChange: (visible: boolean) => void
    onSend: (statusAfterSend?: TicketStatus) => void
    onCancel: () => void
    /** The composer the shortcuts belong to */
    composerRef: React.RefObject<HTMLElement>
    verb: string
    isPrivate: boolean
    channel?: TicketChannel
    audience?: string
    statusLabel?: string
    statusOptions?: { value: TicketStatus; statusLabel: string }[]
    disabledReason?: string | JSX.Element
    loading: boolean
    children: React.ReactNode
}): JSX.Element {
    const choices = statusOptions.slice(0, DIGITS.length)

    // Capture phase, so the keys never reach the editor while the menu is open (Enter would add a line).
    useEffect(() => {
        if (!visible) {
            return
        }
        const onKeyDown = (e: KeyboardEvent): void => {
            // Keys confirm or move inside an IME composition, so leave them to the editor. Safari reports 229.
            if (e.metaKey || e.ctrlKey || e.altKey || e.isComposing || e.keyCode === 229) {
                return
            }
            const target = e.target as HTMLElement
            const inMenu = !!target.closest('.SendMenu')
            // Another focused control, like a ticket sidebar field, keeps its own keys.
            if (!inMenu && target !== document.body && !composerRef.current?.contains(target)) {
                return
            }
            if (e.key === 'Enter') {
                // A focused row inside the menu answers to Enter itself.
                if (inMenu && target.closest('button, a')) {
                    return
                }
                e.preventDefault()
                e.stopPropagation()
                onSend()
                return
            }
            if (e.key === 'Escape') {
                e.preventDefault()
                e.stopPropagation()
                onCancel()
                return
            }
            const index = DIGITS.indexOf(e.key as (typeof DIGITS)[number])
            if (index !== -1 && choices[index]) {
                e.preventDefault()
                e.stopPropagation()
                onSend(choices[index].value)
            }
        }
        document.addEventListener('keydown', onKeyDown, true)
        return () => document.removeEventListener('keydown', onKeyDown, true)
    }, [visible, onSend, onCancel, choices, composerRef])

    const items: LemonMenuItem[] = [
        {
            label: verb,
            icon: <IconSend />,
            keyboardShortcut: ['enter'],
            onClick: () => onSend(),
        },
        ...choices.map(
            (option, i): LemonMenuItem => ({
                key: option.value,
                label: `${verb} and set ${option.statusLabel}`,
                keyboardShortcut: [DIGITS[i]],
                onClick: () => onSend(option.value),
            })
        ),
    ]

    return (
        <LemonMenu
            className="SendMenu"
            visible={visible}
            onVisibilityChange={onVisibilityChange}
            closeOnClickInside={false}
            placement="top-end"
            items={[
                {
                    title: (
                        <div className="min-w-80 px-2 pt-1 pb-2 border-b" data-attr="send-menu">
                            <div className="flex items-center gap-1 text-xs text-secondary">
                                <ReplyIcon isPrivate={isPrivate} channel={channel} />
                                <span>{isPrivate ? 'Private note' : getReplyDestination(channel)}</span>
                            </div>
                            <div className="ph-no-capture font-semibold">
                                {isPrivate ? 'Only your team will see this.' : audience}
                            </div>
                            {statusLabel ? (
                                <div className="text-xs text-secondary">{`Ticket status is ${statusLabel}.`}</div>
                            ) : null}
                        </div>
                    ),
                    items,
                    footer: (
                        <div className="flex items-center justify-between gap-4 px-2 pt-1 border-t text-xs text-secondary">
                            <span>Esc to go back and keep editing</span>
                            <Link onClick={onCancel}>Cancel</Link>
                        </div>
                    ),
                },
            ]}
        >
            <LemonButton type="primary" loading={loading} disabledReason={disabledReason} data-attr="send-menu-trigger">
                {children}
            </LemonButton>
        </LemonMenu>
    )
}
