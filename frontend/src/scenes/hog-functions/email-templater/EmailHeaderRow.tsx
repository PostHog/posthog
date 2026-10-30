import clsx from 'clsx'
import { ReactNode } from 'react'

import { LemonLabel } from '@posthog/lemon-ui'

/** One line of the email header, like From or Subject. Every row shares the label width so the values line up. */
export function EmailHeaderRow({
    label,
    info,
    error,
    className,
    children,
}: {
    label: string
    info?: string
    error?: string | null
    className?: string
    children: ReactNode
}): JSX.Element {
    return (
        <div className={clsx('border-b shrink-0', className)}>
            <div className="flex gap-2 items-center pl-2 pr-1 min-w-0">
                <LemonLabel className={clsx('w-26 shrink-0 whitespace-nowrap', error && 'text-danger')} info={info}>
                    {label}
                </LemonLabel>
                {children}
            </div>
            {/* Starts under the value, past the label column */}
            {error ? <div className="pb-1 pl-30 text-xs text-danger">{error}</div> : null}
        </div>
    )
}
