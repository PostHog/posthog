import { useValues } from 'kea'

import { LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { stripMarkdown } from 'lib/utils/markdown'

import type { TicketMessageApi } from '../../generated/api.schemas'
import { ticketPreviewLogic } from './ticketPreviewLogic'

function TicketPreviewMessage({ message }: { message: TicketMessageApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-1.5">
                <span className="font-semibold text-xs">{message.author_name}</span>
                {message.is_private && (
                    <LemonTag type="muted" size="small">
                        Internal
                    </LemonTag>
                )}
                <span className="text-xs text-muted-alt">
                    <TZLabel time={message.created_at} />
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
            <div className="flex items-center gap-2 p-1">
                <Spinner />
                <span className="text-xs">Loading messages…</span>
            </div>
        )
    }

    if (!preview || preview.messages.length === 0) {
        return <span className="text-xs text-muted-alt">No messages in this ticket yet</span>
    }

    const hiddenCount = preview.totalCount - preview.messages.length

    return (
        <div className="flex flex-col gap-2 py-0.5">
            {preview.messages.map((message) => (
                <TicketPreviewMessage key={message.id} message={message} />
            ))}
            {hiddenCount > 0 && (
                <span className="text-xs text-muted-alt">
                    +{hiddenCount} more {hiddenCount === 1 ? 'message' : 'messages'}
                </span>
            )}
        </div>
    )
}

/**
 * Wraps table cell content with a hover tooltip previewing the ticket's thread,
 * starting from its first message. Messages are fetched lazily on first hover —
 * the tooltip content only mounts once the popup opens.
 */
export function TicketPreviewTooltip({
    ticketId,
    children,
}: {
    ticketId: string
    children: JSX.Element
}): JSX.Element {
    return (
        <Tooltip
            title={<TicketPreviewContent ticketId={ticketId} />}
            placement="bottom-start"
            containerClassName="max-w-100"
            delayMs={300}
        >
            {children}
        </Tooltip>
    )
}
