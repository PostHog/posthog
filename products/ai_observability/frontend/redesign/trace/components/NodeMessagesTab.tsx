import { IconMessage } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { NodeContent } from '../types'
import { ErrorCallout } from './ErrorCallout'
import { IOPanel } from './IOPanel'
import { MessageList } from './MessageList'

export interface NodeMessagesTabProps {
    content: NodeContent
    error: string | null
    onViewInThread: (() => void) | null
}

export function NodeMessagesTab({ content, error, onViewInThread }: NodeMessagesTabProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {error ? <ErrorCallout message={error} /> : null}
            {content.kind === 'loading' ? (
                <LemonSkeleton repeat={3} className="h-16" />
            ) : content.kind === 'error' ? (
                <ErrorCallout message={content.message} />
            ) : content.kind === 'messages' ? (
                <MessageList messages={content.messages} />
            ) : (
                <IOPanel input={content.input} output={content.output} />
            )}
            {onViewInThread && content.kind !== 'loading' ? (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconMessage />}
                    className="self-start"
                    onClick={onViewInThread}
                    data-attr="trace-view-view-in-thread"
                >
                    View in thread
                </LemonButton>
            ) : null}
        </div>
    )
}
