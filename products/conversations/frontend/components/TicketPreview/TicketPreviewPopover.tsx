import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconLock } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Popover } from 'lib/lemon-ui/Popover'
import { stripMarkdown } from 'lib/utils/markdown'

import type { TicketMessageApi } from '../../generated/api.schemas'
import { ticketPreviewLogic } from './ticketPreviewLogic'

function TicketPreviewMessage({ message }: { message: TicketMessageApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-1.5">
                <span className="font-semibold text-xs">{message.author_name}</span>
                {message.is_private && (
                    <span className="inline-flex items-center gap-0.5 text-xs text-warning-dark bg-warning-highlight px-1.5 py-0.5 rounded">
                        <IconLock className="text-xs" />
                        Private note
                    </span>
                )}
                <span className="text-xs text-muted-alt">
                    <TZLabel time={message.created_at} showPopover={false} />
                </span>
            </div>
            <p className="text-xs whitespace-pre-line line-clamp-4 mb-0">{stripMarkdown(message.content)}</p>
        </div>
    )
}

export function TicketPreviewContent({ ticketId }: { ticketId: string }): JSX.Element {
    const { preview, previewLoading } = useValues(ticketPreviewLogic({ ticketId }))

    if (previewLoading && !preview) {
        return (
            <div className="flex items-center gap-2 p-3">
                <Spinner />
                <span className="text-xs">Loading messages…</span>
            </div>
        )
    }

    if (preview?.error) {
        return <span className="text-xs text-muted-alt block p-3">Couldn't load messages</span>
    }

    if (!preview || preview.firstMessages.length === 0) {
        return <span className="text-xs text-muted-alt block p-3">No messages in this ticket yet</span>
    }

    return (
        <div className="flex flex-col gap-2 p-3 max-w-100">
            {preview.firstMessages.map((message) => (
                <TicketPreviewMessage key={message.id} message={message} />
            ))}
            {preview.lastMessage && (
                <>
                    {preview.hiddenCount > 0 && (
                        <div className="flex items-center gap-2 text-xs text-muted-alt">
                            <div className="flex-1 border-t border-primary" />
                            <span className="shrink-0">
                                {preview.hiddenCount} more {preview.hiddenCount === 1 ? 'message' : 'messages'}
                            </span>
                            <div className="flex-1 border-t border-primary" />
                        </div>
                    )}
                    <TicketPreviewMessage message={preview.lastMessage} />
                </>
            )}
        </div>
    )
}

/**
 * Wraps table cell content with a hover card previewing the ticket's thread,
 * starting from its first message. Built on Popover so the card renders on the
 * normal app-theme surface (readable in both light and dark mode). Messages are
 * fetched lazily on first hover — Popover only mounts its overlay once visible.
 */
export function TicketPreviewPopover({ ticketId, children }: { ticketId: string; children: JSX.Element }): JSX.Element {
    const [visible, setVisible] = useState(false)
    const hoverTimerRef = useRef<ReturnType<typeof setTimeout>>()

    useEffect(() => () => clearTimeout(hoverTimerRef.current), [])

    const showPreview = (): void => {
        clearTimeout(hoverTimerRef.current)
        // Hover-intent delay avoids popover spam while sweeping across table rows.
        hoverTimerRef.current = setTimeout(() => setVisible(true), 300)
    }

    const hidePreview = (): void => {
        clearTimeout(hoverTimerRef.current)
        // Grace period so the mouse can travel from the cell into the card.
        hoverTimerRef.current = setTimeout(() => setVisible(false), 300)
    }

    return (
        <Popover
            visible={visible}
            placement="bottom-start"
            showArrow
            onMouseEnterInside={showPreview}
            onMouseLeaveInside={hidePreview}
            overlay={<TicketPreviewContent ticketId={ticketId} />}
        >
            <span onMouseEnter={showPreview} onMouseLeave={hidePreview}>
                {children}
            </span>
        </Popover>
    )
}
