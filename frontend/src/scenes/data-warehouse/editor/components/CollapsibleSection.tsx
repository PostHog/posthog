import clsx from 'clsx'
import { ReactNode } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

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
        <div className={clsx('border-b last:border-b-0 flex flex-col min-h-0', className)}>
            <div
                className={clsx(
                    'flex items-center justify-between gap-4 px-2 py-1 border-b bg-bg-light dark:bg-black',
                    headerClassName
                )}
            >
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={isOpen ? <IconCollapse className="h-4 w-4" /> : <IconExpand className="h-4 w-4" />}
                    onClick={onToggle}
                >
                    <span>{title}</span>
                </LemonButton>
                {actions ? <div className="flex items-center gap-2 flex-shrink-0">{actions}</div> : null}
            </div>
            {isOpen ? <div className={clsx('flex-1 min-h-0 h-full', contentClassName)}>{children}</div> : null}
        </div>
    )
}
