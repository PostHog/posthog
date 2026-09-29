import { cn } from 'lib/utils/css-classes'

import { MessageRole, ThreadMessage } from '../types'
import { MessagePartView } from './MessagePartView'

const ROLE_COLORS: Record<MessageRole, string> = {
    system: 'text-warning',
    user: 'text-[var(--color-blue-700)] dark:text-[var(--color-blue-300)]',
    assistant: 'text-[var(--data-color-14)]',
    tool: 'text-secondary',
}

export interface MessageBlockProps {
    message: ThreadMessage
}

export function MessageBlock({ message }: MessageBlockProps): JSX.Element {
    return (
        <section className="flex flex-col">
            <header
                className={cn(
                    'rounded border border-primary bg-surface-secondary px-3 py-1 font-mono text-xs font-semibold uppercase',
                    ROLE_COLORS[message.role]
                )}
            >
                {message.role}
            </header>
            <div className="flex flex-col gap-2 px-3 py-2 text-sm">
                {message.parts.map((part, index) => (
                    <MessagePartView key={index} part={part} />
                ))}
            </div>
        </section>
    )
}
