import { type ReactNode } from 'react'

import { IconCheck } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

export interface CheckListItem {
    /** Defaults to a green check; pass any icon to override per row. */
    icon?: ReactNode
    content: ReactNode
}

/**
 * A vertical list of icon-led rows — the feature/benefit lists on the plan cards, the install step,
 * and the handoff checklist. Call sites supply data; the row scaffolding lives here once.
 */
export function CheckList({
    items,
    size = 'sm',
    className,
}: {
    items: CheckListItem[]
    /** Row text size; icons scale with it. */
    size?: 'xs' | 'sm'
    className?: string
}): JSX.Element {
    return (
        <ul className={cn('flex flex-col gap-1.5 m-0 p-0 list-none', className)}>
            {items.map((item, i) => (
                <li key={i} className="flex items-start gap-2">
                    {/* The icon box matches the text's first-line height (text-xs → h-4, text-sm → h-5)
                        and centers the icon in it, so single- and multi-line rows align the same way. */}
                    <span
                        className={cn(
                            'shrink-0 text-success flex items-center justify-center',
                            size === 'xs' ? 'h-4 [&_svg]:size-3.5' : 'h-5 [&_svg]:size-4'
                        )}
                    >
                        {item.icon ?? <IconCheck />}
                    </span>
                    <span className={size === 'xs' ? 'text-xs' : 'text-sm'}>{item.content}</span>
                </li>
            ))}
        </ul>
    )
}
