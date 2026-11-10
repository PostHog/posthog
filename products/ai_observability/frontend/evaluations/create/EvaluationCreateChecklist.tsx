import * as stampApprovedPng from '@posthog/brand/hoggies/png/stamp-approved'
import { Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { pluralize } from 'lib/utils/strings'

import type { ChecklistItem } from './creationChecklist'

const ReadyHoggie = pngHoggie(stampApprovedPng)

function ItemLinks({
    items,
    text,
    onOpen,
}: {
    items: ChecklistItem[]
    text: (item: ChecklistItem) => string | undefined
    onOpen: (item: ChecklistItem) => void
}): JSX.Element {
    return (
        <>
            {items.map((item) => (
                <Link key={item.key} className="text-xs" onClick={() => onOpen(item)}>
                    {text(item)}
                </Link>
            ))}
        </>
    )
}

export function EvaluationCreateChecklist({
    checklist,
    startsPaused,
    onOpen,
    children,
}: {
    checklist: ChecklistItem[]
    startsPaused: boolean
    onOpen: (item: ChecklistItem) => void
    children?: React.ReactNode
}): JSX.Element {
    const todo = checklist.filter((item) => !item.done)
    const warnings = checklist.filter((item) => item.done && item.warning)

    if (todo.length > 0) {
        return (
            <div className="flex flex-col gap-1 border-t pt-3" data-attr="llma-evaluation-create-todo">
                <span className="text-xs font-semibold">{`${pluralize(todo.length, 'thing')} left`}</span>
                <ItemLinks items={todo} text={(item) => item.todo} onOpen={onOpen} />
            </div>
        )
    }
    if (warnings.length > 0) {
        return (
            <div className="flex flex-col gap-3 border-t pt-3">
                <div className="flex flex-col gap-1" data-attr="llma-evaluation-create-warnings">
                    <span className="text-xs font-semibold">Check before you create it</span>
                    <ItemLinks items={warnings} text={(item) => item.warning} onOpen={onOpen} />
                </div>
                {children}
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-3 border-t pt-3">
            <div
                className="flex items-center gap-3 animate-fade-in motion-reduce:animate-none"
                data-attr="llma-evaluation-create-ready"
            >
                <ReadyHoggie className="w-12 shrink-0" />
                <span className="flex flex-col">
                    <span className="text-sm font-semibold">Ready to create</span>
                    <span className="text-xs text-secondary">
                        {startsPaused
                            ? 'It starts paused. Add a provider API key, then turn it on.'
                            : 'Everything it needs is set.'}
                    </span>
                </span>
            </div>
            {children}
        </div>
    )
}
