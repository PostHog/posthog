import { cn } from 'lib/utils/css-classes'

import { MessageRole, ThreadMessage } from '../types'
import { MessagePartView } from './MessagePartView'

const ROLE_COLORS: Record<MessageRole, string> = {
    system: 'text-warning',
    user: 'text-[var(--data-color-1)]',
    assistant: 'text-[var(--data-color-14)]',
    tool: 'text-secondary',
}

export interface MessageBlockProps {
    message: ThreadMessage
}

export function MessageBlock({ message }: MessageBlockProps): JSX.Element {
    return (
        <section className="rounded border border-primary bg-surface-primary">
            <header className={cn('px-3 pt-2 font-mono text-xs font-semibold uppercase', ROLE_COLORS[message.role])}>
                {message.role}
            </header>
            <div className="flex flex-col gap-2 px-3 pb-3 pt-1 text-sm">
                {message.parts.map((part, index) => (
                    <MessagePartView key={index} part={part} />
                ))}
            </div>
        </section>
    )
}
