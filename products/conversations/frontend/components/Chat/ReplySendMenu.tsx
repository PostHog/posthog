import { useEffect, useRef } from 'react'

import { IconLock, IconSend } from '@posthog/icons'
import { LemonButton, LemonDropdown, Link, Tooltip } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'

import type { TicketChannel, TicketStatus } from '../../types'
import { channelIcon, getReplyDestination } from '../Channels/ChannelsTag'

export interface SimplifiedRepliesProps {
    /** Who the reply reaches, e.g. the customer's email address or name */
    recipient?: string | null
    /** The ticket's saved status, e.g. "Open" */
    statusLabel?: string
}

const DIGITS = ['1', '2', '3', '4', '5', '6', '7', '8', '9'] as const

function ReplyIcon({ isPrivate, channel }: { isPrivate: boolean; channel?: TicketChannel }): JSX.Element {
    if (isPrivate) {
        return <IconLock />
    }
    return channel ? channelIcon[channel] : <IconSend />
}

/** Names where the reply goes and who it reaches before the first word, and keeps saying it after the placeholder is gone. */
export function ComposerHeader({
    isPrivate,
    channel,
    recipient,
    statusLabel,
}: SimplifiedRepliesProps & { isPrivate: boolean; channel?: TicketChannel }): JSX.Element {
    const detail = isPrivate ? 'Only your team will see this' : recipient
    return (
        <div className="flex items-center gap-2 px-2 py-1 text-xs" data-attr="composer-header">
            <span className="flex text-sm">
                <ReplyIcon isPrivate={isPrivate} channel={channel} />
            </span>
            <span className="font-semibold shrink-0">{isPrivate ? 'Private note' : getReplyDestination(channel)}</span>
            {detail ? (
                <Tooltip title={<span className="ph-no-capture">{detail}</span>}>
                    <span className="ph-no-capture truncate text-secondary min-w-0">{detail}</span>
                </Tooltip>
            ) : null}
            {statusLabel ? <span className="ml-auto shrink-0 text-secondary">Ticket status: {statusLabel}</span> : null}
        </div>
    )
}

/**
 * One Send button in place of the split button and draft mode. It never sends on its own: it opens a menu
 * that says where the reply goes and lists every way to send, each naming the status the ticket is left in.
 * While open, Enter sends, a digit picks the numbered status, Escape goes back to the draft.
 */
export function SendMenu({
    visible,
    onVisibilityChange,
    onSend,
    onCancel,
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
    const overlayRef = useRef<HTMLDivElement>(null)
    const choices = statusOptions.slice(0, DIGITS.length)

    // Capture phase, so the keys never reach the editor while the menu is open (Enter would add a line).
    useEffect(() => {
        if (!visible) {
            return
        }
        const onKeyDown = (e: KeyboardEvent): void => {
            if (e.metaKey || e.ctrlKey || e.altKey) {
                return
            }
            const target = e.target as HTMLElement | null
            if (e.key === 'Enter') {
                // A focused row inside the menu answers to Enter itself.
                if (target && overlayRef.current?.contains(target) && target.closest('button, a')) {
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
    }, [visible, onSend, onCancel, choices])

    return (
        <LemonDropdown
            visible={visible}
            onVisibilityChange={onVisibilityChange}
            closeOnClickInside={false}
            placement="top-end"
            overlay={
                <div ref={overlayRef} className="min-w-80" data-attr="send-menu">
                    <div className="px-2 pt-1 pb-2 border-b">
                        <div className="flex items-center gap-1 text-xs text-secondary">
                            <ReplyIcon isPrivate={isPrivate} channel={channel} />
                            {isPrivate ? 'Private note' : getReplyDestination(channel)}
                        </div>
                        <div className="ph-no-capture font-semibold">
                            {isPrivate ? 'Only your team will see this.' : audience}
                        </div>
                        {statusLabel ? (
                            <div className="text-xs text-secondary">Ticket status is {statusLabel}.</div>
                        ) : null}
                    </div>
                    <div className="py-1">
                        <LemonButton
                            fullWidth
                            size="small"
                            icon={<IconSend />}
                            sideIcon={<KeyboardShortcut enter />}
                            onClick={() => onSend()}
                        >
                            {verb}
                        </LemonButton>
                        {choices.map((option, i) => (
                            <LemonButton
                                key={option.value}
                                fullWidth
                                size="small"
                                sideIcon={<KeyboardShortcut {...{ [DIGITS[i]]: true }} />}
                                onClick={() => onSend(option.value)}
                            >
                                {`${verb} and set ${option.statusLabel}`}
                            </LemonButton>
                        ))}
                    </div>
                    <div className="flex items-center justify-between gap-4 px-2 pt-1 border-t text-xs text-secondary">
                        <span>Esc to go back and keep editing</span>
                        <Link onClick={onCancel}>Cancel</Link>
                    </div>
                </div>
            }
        >
            <LemonButton type="primary" loading={loading} disabledReason={disabledReason}>
                {children}
            </LemonButton>
        </LemonDropdown>
    )
}
