import clsx from 'clsx'
import { ReactNode } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'

interface CollapsibleSectionProps {
    title: string
    isOpen: boolean
    onToggle: () => void
    actions?: ReactNode
    children?: ReactNode
    className?: string
    contentClassName?: string
    headerClassName?: string
}

export function CollapsibleSection({
    title,
    isOpen,
    onToggle,
    actions,
    children,
    className,
    contentClassName,
    headerClassName,
}: CollapsibleSectionProps): JSX.Element {
    return (
        <div className={clsx('border-b last:border-b-0', className)}>
            <div className={clsx('flex items-center justify-between gap-4 px-2 py-1', headerClassName)}>
                <button
                    type="button"
                    className="flex items-center gap-1 text-sm font-semibold text-default hover:text-primary"
                    onClick={onToggle}
                    aria-expanded={isOpen}
                >
                    {isOpen ? <IconCollapse className="h-4 w-4" /> : <IconExpand className="h-4 w-4" />}
                    <span>{title}</span>
                </button>
                {actions ? <div className="flex items-center gap-2 flex-shrink-0">{actions}</div> : null}
            </div>
            {isOpen ? <div className={clsx('min-h-0', contentClassName)}>{children}</div> : null}
        </div>
    )
}
