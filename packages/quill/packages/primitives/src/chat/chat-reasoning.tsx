import { Collapsible as CollapsiblePrimitive } from '@base-ui/react/collapsible'
import { BrainIcon, ChevronRightIcon } from 'lucide-react'
import * as React from 'react'

import './chat-reasoning.css'
import './lib/disclosure.css'
import { cn } from '../lib/utils'

/**
 * The agent's reasoning stream — a shimmering "Thinking…" row while the model works, collapsing
 * into a "Thought for Ns" summary the reader can reopen. Adapted from the aicss thinking/reasoning
 * pattern onto quill tokens + Base UI Collapsible. Styling lives in `chat-reasoning.css`.
 *
 * `status` drives everything: while `thinking` the panel is force-open, the trigger is inert, and
 * the viewport pins to the newest step (steps stream in, older ones fade off the top). On `done`
 * the row becomes a real Collapsible trigger honouring `defaultOpen`/`open`. Steps are the app's
 * to append — this primitive owns the reveal, the height cap, and the fade masks, not the timing.
 */
type ChatReasoningStatus = 'thinking' | 'done'

type ChatReasoningContextValue = {
    status: ChatReasoningStatus
    open: boolean
}

const ChatReasoningContext = React.createContext<ChatReasoningContextValue | null>(null)

function useChatReasoningContext(slot: string): ChatReasoningContextValue {
    const context = React.useContext(ChatReasoningContext)
    if (!context) {
        throw new Error(`${slot} must be used within a ChatReasoning`)
    }
    return context
}

type CollapsibleRootProps = React.ComponentProps<typeof CollapsiblePrimitive.Root>
type OpenChangeHandler = NonNullable<CollapsibleRootProps['onOpenChange']>

type ChatReasoningProps = CollapsibleRootProps & {
    /** `thinking` shimmers the label and pins the stream to its newest step; `done` unlocks the toggle. */
    status?: ChatReasoningStatus
}

function ChatReasoning({
    status = 'thinking',
    className,
    defaultOpen = false,
    open: openProp,
    onOpenChange,
    ...props
}: ChatReasoningProps): React.ReactElement {
    const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen)
    const open = openProp ?? uncontrolledOpen

    const handleOpenChange = React.useCallback<OpenChangeHandler>(
        (next, eventDetails) => {
            setUncontrolledOpen(next)
            onOpenChange?.(next, eventDetails)
        },
        [onOpenChange]
    )

    const thinking = status === 'thinking'
    const context = React.useMemo(() => ({ status, open: thinking || open }), [status, thinking, open])

    return (
        <ChatReasoningContext.Provider value={context}>
            <CollapsiblePrimitive.Root
                data-quill
                data-slot="reasoning"
                data-status={status}
                open={context.open}
                onOpenChange={handleOpenChange}
                className={cn('quill-chat-reasoning', className)}
                {...props}
            />
        </ChatReasoningContext.Provider>
    )
}

function ChatReasoningTrigger({
    className,
    children,
    ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.Trigger>): React.ReactElement {
    const { status } = useChatReasoningContext('ChatReasoningTrigger')
    const thinking = status === 'thinking'

    return (
        <CollapsiblePrimitive.Trigger
            data-slot="reasoning-trigger"
            // Force-open while thinking, so there's nothing to toggle. Base UI marks this with
            // `aria-disabled` and keeps the tab stop, so the row still announces itself; the CSS
            // gates its hover fill and pointer off the same attribute.
            disabled={thinking}
            className={cn('quill-chat-row', 'quill-chat-row--interactive', 'quill-chat-reasoning__trigger', className)}
            {...props}
        >
            <span data-slot="reasoning-icon" aria-hidden="true" className="quill-chat-swap">
                <span
                    className={cn(
                        'quill-chat-bullet',
                        'quill-chat-swap__icon',
                        // The icon carries the same "live" signal as the label beside it, on the same
                        // cadence — a sweep across the row, not two unrelated animations.
                        thinking && 'quill-chat-shimmer-icon'
                    )}
                >
                    <BrainIcon />
                </span>
                {/* No chevron while thinking: the panel is force-open, so there's nothing to toggle. */}
                {!thinking && (
                    <ChevronRightIcon
                        aria-hidden="true"
                        className={cn('quill-chat-chevron', 'quill-chat-swap__chevron')}
                    />
                )}
            </span>
            {children}
        </CollapsiblePrimitive.Trigger>
    )
}

function ChatReasoningLabel({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    const { status } = useChatReasoningContext('ChatReasoningLabel')
    return (
        <span
            data-slot="reasoning-label"
            className={cn('quill-chat-reasoning__label', status === 'thinking' && 'quill-chat-shimmer', className)}
            {...props}
        />
    )
}

function ChatReasoningContent({ className, children, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    const { status, open } = useChatReasoningContext('ChatReasoningContent')
    const thinking = status === 'thinking'
    const viewportRef = React.useRef<HTMLDivElement>(null)
    const streamRef = React.useRef<HTMLDivElement>(null)

    // Written straight to the DOM rather than through state: this runs on every scroll frame and on
    // every step, and a re-render per frame is how you drop them.
    const sync = React.useCallback(() => {
        const viewport = viewportRef.current
        const stream = streamRef.current
        if (!viewport || !stream) {
            return
        }
        const setFade = (top: boolean, bottom: boolean): void => {
            viewport.toggleAttribute('data-fade-top', top)
            viewport.toggleAttribute('data-fade-bottom', bottom)
        }
        // While thinking the reader follows the newest step, so the stream stays bottom-anchored.
        // Anchoring by transform rather than scrollTop keeps the travel on the compositor and lets
        // it ease — a scroll jump would teleport the older steps. A transform doesn't affect layout,
        // so the viewport still sizes to the stream (capped), and the overflow is what we slide by.
        if (thinking) {
            const overflow = Math.max(0, stream.offsetHeight - viewport.clientHeight)
            stream.style.setProperty('--quill-chat-reasoning-offset', `${-overflow}px`)
            // Nothing sits below the newest step, so only the top edge needs softening.
            setFade(overflow > 0, false)
            return
        }
        stream.style.setProperty('--quill-chat-reasoning-offset', '0px')
        setFade(viewport.scrollTop > 1, viewport.scrollTop + viewport.clientHeight < viewport.scrollHeight - 1)
    }, [thinking])

    // Steps stream in one by one, so the stream box resizes rather than re-rendering this component.
    React.useLayoutEffect(() => {
        const stream = streamRef.current
        if (!stream) {
            return
        }
        const observer = new ResizeObserver(sync)
        observer.observe(stream)
        return () => observer.disconnect()
    }, [sync])

    React.useLayoutEffect(() => {
        const viewport = viewportRef.current
        if (open && !thinking && viewport) {
            viewport.scrollTop = 0
        }
        sync()
    }, [open, thinking, sync])

    return (
        <CollapsiblePrimitive.Panel
            data-slot="reasoning-panel"
            className={cn('quill-chat-collapse', 'quill-chat-reasoning__panel')}
        >
            <div
                ref={viewportRef}
                data-slot="reasoning-viewport"
                onScroll={sync}
                className={cn('quill-chat-rail', 'quill-chat-reasoning__viewport', className)}
                {...props}
            >
                <div ref={streamRef} data-slot="reasoning-stream" className="quill-chat-reasoning__stream">
                    {children}
                </div>
            </div>
        </CollapsiblePrimitive.Panel>
    )
}

function ChatReasoningStep({ className, ...props }: React.ComponentProps<'p'>): React.ReactElement {
    return <p data-slot="reasoning-step" className={cn('quill-chat-reasoning__step', className)} {...props} />
}

export { ChatReasoning, ChatReasoningTrigger, ChatReasoningLabel, ChatReasoningContent, ChatReasoningStep }
