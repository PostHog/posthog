import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { ArrowUpRightIcon, CircleCheckIcon, CircleDashedIcon } from 'lucide-react'
import * as React from 'react'

import './chat-source.css'
import './lib/status.css'
import { cn } from '../lib/utils'
import { ChatGlobe } from './chat-globe'

/**
 * A page an agent found and read — the rows a web search discloses. Vendored from the aicss
 * web-search pattern and renamed `ChatSource`. Drop a `ChatSourceList` into a `ChatMarker`'s `body`.
 *
 * `status` walks a row through the fetch: `pending` (found, not opened) shows a dashed ring,
 * `loading` swaps in a sweeping {@link ./chat-globe#ChatGlobe}, `done` lands on a check. The app owns
 * when each row moves — same contract as the rest of the family, since only the app knows what the
 * agent is actually doing.
 *
 * Give a row an `href` and it becomes a link with an out-arrow; without one it's static text.
 */
type ChatSourceStatus = 'pending' | 'loading' | 'done'

const STATUS_ICON: Record<ChatSourceStatus, React.ReactElement> = {
    pending: <CircleDashedIcon />,
    loading: <ChatGlobe />,
    done: <CircleCheckIcon />,
}

function ChatSourceList({ className, ...props }: React.ComponentProps<'ul'>): React.ReactElement {
    return <ul data-quill data-slot="source-list" className={cn('quill-chat-source-list', className)} {...props} />
}

type ChatSourceProps = useRender.ComponentProps<'a'> & {
    status?: ChatSourceStatus
    href?: string
}

function ChatSource({
    status = 'pending',
    className,
    children,
    href,
    render,
    ...props
}: ChatSourceProps): React.ReactElement {
    const row = useRender({
        defaultTagName: href == null ? 'span' : 'a',
        props: mergeProps<'a'>(
            {
                'data-slot': 'source',
                href,
                className: cn('quill-chat-source', className),
                children: (
                    <>
                        <span data-slot="source-bullet" data-status={status} className="quill-chat-bullet">
                            {/* Keyed so a status change mounts a fresh icon, which replays the reveal. */}
                            <React.Fragment key={status}>{STATUS_ICON[status]}</React.Fragment>
                        </span>
                        {children}
                        {href != null && <ArrowUpRightIcon aria-hidden="true" className="quill-chat-source__arrow" />}
                    </>
                ),
            } as Omit<React.ComponentProps<'a'>, 'ref'>,
            props
        ),
        render,
        state: { slot: 'source', status },
    })

    return (
        <li data-status={status} className="quill-chat-source-item">
            {row}
        </li>
    )
}

function ChatSourceTitle({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="source-title" className={cn('quill-chat-source__title', className)} {...props} />
}

function ChatSourceUrl({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="source-url" className={cn('quill-chat-source__url', className)} {...props} />
}

export { ChatSourceList, ChatSource, ChatSourceTitle, ChatSourceUrl, type ChatSourceStatus }
