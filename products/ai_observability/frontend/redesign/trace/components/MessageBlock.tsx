import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { MessageRole, ThreadMessage } from '../types'
import { MessagePartView } from './MessagePartView'

const ROLE_COLORS: Record<MessageRole, string> = {
    system: 'text-warning',
    user: 'text-[var(--color-blue-700)] dark:text-[var(--color-blue-300)]',
    assistant: 'text-[var(--data-color-14)]',
    tool: 'text-secondary',
}

function previewText(message: ThreadMessage): string | null {
    for (const part of message.parts) {
        if (part.kind === 'text') {
            return part.text
        }
    }
    return null
}

export interface MessageBlockProps {
    message: ThreadMessage
    defaultOpen: boolean
}

export function MessageBlock({ message, defaultOpen }: MessageBlockProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(defaultOpen)
    const preview = isOpen ? null : previewText(message)

    return (
        <section className="flex flex-col">
            <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setIsOpen(!isOpen)}
                data-attr="trace-view-message-toggle"
                className="flex min-w-0 items-center gap-1.5 rounded border border-primary bg-surface-secondary px-2 py-1 text-left hover:bg-fill-button-tertiary-hover"
            >
                <IconChevronRight
                    className={cn('shrink-0 text-secondary transition-transform motion-reduce:transition-none', {
                        'rotate-90': isOpen,
                    })}
                />
                <span className={cn('shrink-0 font-mono text-xs font-semibold uppercase', ROLE_COLORS[message.role])}>
                    {message.role}
                </span>
                {preview ? <span className="min-w-0 truncate text-xs text-secondary">{preview}</span> : null}
            </button>
            {isOpen ? (
                <div className="flex flex-col gap-2 px-3 py-2 text-sm">
                    {message.parts.map((part, index) => (
                        <MessagePartView key={index} part={part} />
                    ))}
                </div>
            ) : null}
        </section>
    )
}
