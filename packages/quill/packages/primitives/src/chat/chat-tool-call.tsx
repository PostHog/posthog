import { Collapsible as CollapsiblePrimitive } from '@base-ui/react/collapsible'
import { ChevronRightIcon } from 'lucide-react'
import * as React from 'react'

import './chat-tool-call.css'
import './lib/disclosure.css'
import { cn } from '../lib/utils'

/**
 * What the agent did, and the detail behind it. The row is the joined-up summary — "Read 2 files ·
 * Edited 1 file", "Searched 3 sources" — and discloses the individual calls below it.
 *
 * The summary carries no icon: it stands for several calls at once, and no single icon is honest
 * about that. Icons belong on the rows inside, where each one names one tool. Use `ChatMarker` for
 * those (icon + text is exactly what it is), or `ChatSourceList` when the tool returned pages.
 *
 * Sibling primitives, so you pick by what happened rather than by how it looks: {@link
 * ./chat-reasoning#ChatReasoning} is the model thinking (no tool ran, and its stream is capped and
 * pinned); {@link ./chat-marker#ChatMarker} is a settled status note with no live state. All three
 * share the row, rail, and shimmer from `lib/disclosure.css`.
 *
 * `status` only tints the label — unlike reasoning, the panel is yours to open at any point, since a
 * reader may want the sources either while they arrive or long after. `error` is a call that came
 * back wrong: the shimmer stops and the row goes destructive, but the results stay readable, since
 * what a failing tool did return is usually the whole story.
 */
type ChatToolCallStatus = 'running' | 'done' | 'error'

const ChatToolCallContext = React.createContext<ChatToolCallStatus>('done')

type ChatToolCallProps = React.ComponentProps<typeof CollapsiblePrimitive.Root> & {
    /** `running` shimmers the label, `error` tints it destructive. The app flips it; never inferred. */
    status?: ChatToolCallStatus
}

function ChatToolCall({ status = 'running', className, ...props }: ChatToolCallProps): React.ReactElement {
    return (
        <ChatToolCallContext.Provider value={status}>
            <CollapsiblePrimitive.Root
                data-quill
                data-slot="tool-call"
                data-status={status}
                className={cn('quill-chat-tool-call', className)}
                {...props}
            />
        </ChatToolCallContext.Provider>
    )
}

function ChatToolCallTrigger({
    className,
    children,
    ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.Trigger>): React.ReactElement {
    return (
        <CollapsiblePrimitive.Trigger
            data-slot="tool-call-trigger"
            className={cn('quill-chat-row', 'quill-chat-row--interactive', 'quill-chat-tool-call__trigger', className)}
            {...props}
        >
            {children}
            {/* Trailing and hidden until you reach for it, like ChatMarker's — a transcript of these
                shouldn't read as a wall of controls. */}
            <ChevronRightIcon
                aria-hidden="true"
                className={cn('quill-chat-chevron', 'quill-chat-chevron--reveal')}
            />
        </CollapsiblePrimitive.Trigger>
    )
}

function ChatToolCallLabel({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    const status = React.useContext(ChatToolCallContext)
    return (
        <span
            data-slot="tool-call-label"
            className={cn('quill-chat-tool-call__label', status === 'running' && 'quill-chat-shimmer', className)}
            {...props}
        />
    )
}

/** The call's argument — the query, the path, the command. Quoted and tinted away from the verb. */
function ChatToolCallValue({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="tool-call-value" className={cn('quill-chat-tool-call__value', className)} {...props} />
}

function ChatToolCallContent({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <CollapsiblePrimitive.Panel
            data-slot="tool-call-panel"
            className={cn('quill-chat-collapse', 'quill-chat-rail', 'quill-chat-tool-call__panel', className)}
            {...props}
        />
    )
}

export {
    ChatToolCall,
    ChatToolCallTrigger,
    ChatToolCallLabel,
    ChatToolCallValue,
    ChatToolCallContent,
    type ChatToolCallStatus,
}
