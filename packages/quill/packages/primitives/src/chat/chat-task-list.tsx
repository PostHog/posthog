import './chat-task-list.css'
import './lib/disclosure.css'
import './lib/status.css'

import { Collapsible as CollapsiblePrimitive } from '@base-ui/react/collapsible'
import {
    ChevronRightIcon,
    CircleArrowRightIcon,
    CircleCheckIcon,
    CircleDashedIcon,
    CircleXIcon,
    ListIcon,
} from 'lucide-react'
import * as React from 'react'

import { useReducedMotion } from '../lib/use-reduced-motion'
import { cn } from '../lib/utils'

/**
 * The plan an agent is working through — a checklist that fills in as steps land. Adapted from the
 * aicss to-do list pattern. Sibling of {@link ./chat-marker#ChatMarker}, which covers what the agent
 * *did* — a note, a call, a group of them. This is the *plan*: many steps, an aggregate count, and
 * each step carrying its own outcome.
 *
 * The list holds no state. `value`/`total` are the app's count of finished steps, and every `ChatTask`
 * carries its own `status` — nothing is inferred from the children, because only the app knows which
 * step is running or why one broke.
 *
 * It's the same primitive whether the steps are to-dos or a sandbox booting; only the copy and the
 * statuses differ. There's no `variant` — a checklist is a checklist.
 *
 * Steps wrap by default; pass `truncate` to a `ChatTask` to clamp it to one line instead.
 */
type ChatTaskStatus = 'pending' | 'active' | 'done' | 'failed'

const TASK_ICON: Record<ChatTaskStatus, React.ReactElement> = {
    pending: <CircleDashedIcon />,
    active: <CircleArrowRightIcon />,
    done: <CircleCheckIcon />,
    failed: <CircleXIcon />,
}

type ChatTaskListContextValue = {
    value: number
    total: number
}

const ChatTaskListContext = React.createContext<ChatTaskListContextValue | null>(null)

function useChatTaskListContext(slot: string): ChatTaskListContextValue {
    const context = React.useContext(ChatTaskListContext)
    if (!context) {
        throw new Error(`${slot} must be used within a ChatTaskList`)
    }
    return context
}

type ChatTaskListProps = React.ComponentProps<typeof CollapsiblePrimitive.Root> & {
    /** Steps finished so far. Drives the header icon and the count; never inferred from children. */
    value: number
    /** Steps in the plan. */
    total: number
}

function ChatTaskList({ value, total, className, ...props }: ChatTaskListProps): React.ReactElement {
    const context = React.useMemo(() => ({ value, total }), [value, total])

    return (
        <ChatTaskListContext.Provider value={context}>
            <CollapsiblePrimitive.Root
                data-quill
                data-slot="task-list"
                className={cn('quill-chat-task-list', className)}
                {...props}
            />
        </ChatTaskListContext.Provider>
    )
}

function ChatTaskListTrigger({
    className,
    children,
    ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.Trigger>): React.ReactElement {
    return (
        <CollapsiblePrimitive.Trigger
            data-slot="task-list-trigger"
            className={cn('quill-chat-row', 'quill-chat-row--interactive', 'quill-chat-task-list__trigger', className)}
            {...props}
        >
            {children}
        </CollapsiblePrimitive.Trigger>
    )
}

/**
 * The header's at-a-glance state: a list before anything starts, a ring that fills as steps land, a
 * check once they all have. Derived from `value`/`total`, so it can't drift from the count beside it.
 *
 * It doubles as the disclosure affordance: hovering or focusing the row swaps the state icon for a
 * chevron, the same trade `CollapsibleTrigger`'s `icon` prop makes. The state is what you want at
 * rest; the chevron only matters once you've reached for it, so it doesn't need to sit there
 * permanently taking up the row.
 */
function ChatTaskListProgress({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    const { value, total } = useChatTaskListContext('ChatTaskListProgress')
    const done = total > 0 && value >= total

    return (
        <span
            data-slot="task-list-progress"
            aria-hidden="true"
            className={cn('quill-chat-swap', 'quill-chat-task-list__progress', className)}
            {...props}
        >
            <span
                data-slot="task-list-progress-icon"
                data-status={done ? 'done' : undefined}
                className={cn('quill-chat-bullet', 'quill-chat-swap__icon')}
            >
                {value <= 0 ? <ListIcon /> : done ? <CircleCheckIcon /> : <ProgressRing value={value} total={total} />}
            </span>
            <ChevronRightIcon aria-hidden="true" className={cn('quill-chat-chevron', 'quill-chat-swap__chevron')} />
        </span>
    )
}

function ProgressRing({ value, total }: { value: number; total: number }): React.ReactElement {
    // `pathLength` renormalizes the circle to 100 user units, so the arc is the percentage itself —
    // no circumference math, and no inline style to carry it.
    const percent = Math.round((Math.min(Math.max(value, 0), total) / total) * 100)

    return (
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" className="quill-chat-task-list__ring">
            <circle
                className="quill-chat-task-list__ring-track"
                cx="12"
                cy="12"
                r="10.5"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeDasharray="2.2 4.4"
                strokeLinecap="round"
            />
            <circle
                className="quill-chat-task-list__ring-fill"
                cx="12"
                cy="12"
                r="10.5"
                pathLength="100"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeDasharray={`${percent} 100`}
                strokeLinecap="round"
            />
        </svg>
    )
}

function ChatTaskListLabel({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="task-list-label" className={cn('quill-chat-task-list__label', className)} {...props} />
}

/**
 * `2/5`, where each digit rolls to its successor. The rolling glyphs are decorative — the real value
 * goes to screen readers once, as text, instead of announcing a half-rolled pair.
 */
function ChatTaskListCount({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    const { value, total } = useChatTaskListContext('ChatTaskListCount')
    const shown = `${Math.min(Math.max(value, 0), total)}/${total}`

    return (
        <span data-slot="task-list-count" className={cn('quill-chat-task-list__count', className)} {...props}>
            <span className="sr-only">
                {Math.min(Math.max(value, 0), total)} of {total} done
            </span>
            <span aria-hidden="true" className="quill-chat-task-list__digits">
                {shown.split('').map((char, index) => (
                    // Digits are positional: index is the identity here, the glyph is the value.
                    // eslint-disable-next-line react/no-array-index-key
                    <RollingChar key={index} char={char} />
                ))}
            </span>
        </span>
    )
}

const ROLL_MS = 250

function RollingChar({ char }: { char: string }): React.ReactElement {
    const previous = React.useRef(char)
    const [roll, setRoll] = React.useState<{ from: string; to: string } | null>(null)
    const reducedMotion = useReducedMotion()

    React.useEffect(() => {
        if (char === previous.current) {
            return
        }
        const from = previous.current
        previous.current = char
        if (reducedMotion) {
            return
        }
        setRoll({ from, to: char })
        const timer = setTimeout(() => setRoll(null), ROLL_MS)
        return () => clearTimeout(timer)
    }, [char, reducedMotion])

    if (!roll) {
        return <span className="quill-chat-task-list__char">{char}</span>
    }

    return (
        <span className="quill-chat-task-list__char">
            <span className="quill-chat-task-list__char-roll">
                <span>{roll.from}</span>
                <span>{roll.to}</span>
            </span>
        </span>
    )
}

function ChatTaskListContent({ className, children, ...props }: React.ComponentProps<'ol'>): React.ReactElement {
    return (
        <CollapsiblePrimitive.Panel
            data-slot="task-list-panel"
            className={cn('quill-chat-collapse', 'quill-chat-rail', 'quill-chat-task-list__panel')}
        >
            <ol data-slot="task-list-items" className={cn('quill-chat-task-list__items', className)} {...props}>
                {children}
            </ol>
        </CollapsiblePrimitive.Panel>
    )
}

type ChatTaskProps = React.ComponentProps<'li'> & {
    status?: ChatTaskStatus
    /** Clamp the label to one line with an ellipsis. Off by default — a long step wraps. */
    truncate?: boolean
}

function ChatTask({
    status = 'pending',
    truncate = false,
    className,
    children,
    ...props
}: ChatTaskProps): React.ReactElement {
    return (
        <li
            data-slot="task"
            data-status={status}
            className={cn('quill-chat-task', truncate && 'quill-chat-task--truncate', className)}
            {...props}
        >
            <span data-status={status} className="quill-chat-bullet">
                {/* Keyed so a status change mounts a fresh icon, which replays the reveal. */}
                <React.Fragment key={status}>{TASK_ICON[status]}</React.Fragment>
            </span>
            {/* The running step is live work, so it shimmers like every other live row in the family. */}
            <span
                data-slot="task-label"
                className={cn('quill-chat-task__label', status === 'active' && 'quill-shimmer')}
            >
                {children}
            </span>
        </li>
    )
}

/** What the step produced: a duration, an exit code, the line that explains a failure. */
function ChatTaskDetail({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="task-detail" className={cn('quill-chat-task__detail', className)} {...props} />
}

export {
    ChatTaskList,
    ChatTaskListTrigger,
    ChatTaskListProgress,
    ChatTaskListLabel,
    ChatTaskListCount,
    ChatTaskListContent,
    ChatTask,
    ChatTaskDetail,
    type ChatTaskStatus,
}
