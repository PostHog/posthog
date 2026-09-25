import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { ThreadMessage } from '../types'
import { MessagePartView } from './MessagePartView'

export interface ThreadBubbleProps {
    message: ThreadMessage
    onSelect?: () => void
}

export function ThreadBubble({ message, onSelect }: ThreadBubbleProps): JSX.Element {
    const isUser = message.role === 'user'
    const baseClassName = cn(
        'flex flex-col gap-2 text-left text-sm',
        isUser ? 'max-w-4/5 self-end rounded-lg bg-fill-highlight-100 px-3 py-2' : 'self-stretch',
        message.isInternal && 'text-secondary'
    )

    const content = message.parts.map((part, index) => <MessagePartView key={index} part={part} />)

    if (!onSelect) {
        return <div className={baseClassName}>{content}</div>
    }

    return (
        <div className={cn(baseClassName, 'flex-row items-start justify-between')}>
            <div className="flex min-w-0 flex-col gap-2">{content}</div>
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
