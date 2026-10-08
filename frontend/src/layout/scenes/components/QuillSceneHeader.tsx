import type { ReactNode } from 'react'

import { cn } from '@posthog/quill'

export interface QuillSceneHeaderProps {
    back?: ReactNode
    icon?: ReactNode
    title: ReactNode
    actions?: ReactNode
    className?: string
}

/**
 * The title bar under the Today layout, for both a scene and the sidebar pane beside it. One component with a fixed
 * height keeps the two bottom borders in one line across the window.
 */
export function QuillSceneHeader({ back, icon, title, actions, className }: QuillSceneHeaderProps): JSX.Element {
    return (
        <header
            data-quill
            className={cn(
                'flex h-12 shrink-0 items-center gap-1 border-b border-[var(--border)] px-4',
                '@max-xl/main-content:h-auto @max-xl/main-content:min-h-12 @max-xl/main-content:flex-wrap @max-xl/main-content:gap-y-2 @max-xl/main-content:py-2',
                className
            )}
        >
            {back}
            {icon && (
                <span className="flex size-4 shrink-0 items-center justify-center text-sm [&_svg]:size-4" aria-hidden>
                    {icon}
                </span>
            )}
            <div className="flex min-w-0 flex-1 items-center gap-1 @max-xl/main-content:min-w-48">{title}</div>
            {actions && (
                <div className="ml-auto flex shrink-0 items-center gap-1 @max-xl/main-content:shrink @max-xl/main-content:flex-wrap @max-xl/main-content:justify-end">
                    {actions}
                </div>
            )}
        </header>
    )
}
