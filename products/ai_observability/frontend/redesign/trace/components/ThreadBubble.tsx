import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { ThreadMessage } from '../types'
import { MessagePartView } from './MessagePartView'
import { ShowMore } from './ShowMore'

export interface ThreadBubbleProps {
    message: ThreadMessage
    onSelect?: () => void
    isFaded?: boolean
    highlightQuery?: string | null
}

export function ThreadBubble({
    message,
    onSelect,
    isFaded = false,
    highlightQuery = null,
}: ThreadBubbleProps): JSX.Element {
    const isUser = message.role === 'user'
    const baseClassName = cn(
        'flex flex-col gap-2 text-left text-sm',
        'max-w-4/5 rounded-lg px-3 py-2',
        isUser ? 'self-end bg-fill-highlight-100' : 'self-start border border-primary bg-surface-primary',
        message.isInternal && 'text-secondary',
        isFaded && 'opacity-50'
    )

    const content = (
        <ShowMore highlightQuery={highlightQuery}>
            {message.parts.map((part, index) => (
                <MessagePartView key={index} part={part} highlightQuery={highlightQuery} />
            ))}
        </ShowMore>
    )

    if (!onSelect) {
        return <div className={baseClassName}>{content}</div>
    }

    return (
        <div className={cn(baseClassName, 'flex-row items-start justify-between')}>
            {content}
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconArrowRight />}
                onClick={onSelect}
                tooltip="View this step"
                aria-label="View this step"
                data-attr="trace-view-thread-view-step"
            />
        </div>
    )
}
