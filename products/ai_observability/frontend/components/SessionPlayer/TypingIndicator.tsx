import { MessageTemplate } from 'products/posthog_ai/frontend/api/primitives'

// Chat-app typing dots shown while a turn is in flight; `type` picks the side.
export function TypingIndicator({ type = 'ai' }: { type?: 'human' | 'ai' }): JSX.Element {
    return (
        <MessageTemplate type={type} wrapperClassName="max-w-[75%]">
            <span
                className="flex gap-1 items-center py-0.5"
                aria-label={type === 'human' ? 'User is typing' : 'Assistant is responding'}
            >
                <span className="w-1.5 h-1.5 rounded-full bg-muted animate-bounce" />
                <span className="w-1.5 h-1.5 rounded-full bg-muted animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-muted animate-bounce [animation-delay:300ms]" />
            </span>
        </MessageTemplate>
    )
}
