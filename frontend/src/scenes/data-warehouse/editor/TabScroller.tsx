import clsx from 'clsx'
import type { HTMLAttributes, ReactNode } from 'react'

type TabScrollerProps = HTMLAttributes<HTMLDivElement> & {
    children: ReactNode
}

export default function TabScroller({ children, className, ...props }: TabScrollerProps): JSX.Element {
    return (
        <div className={clsx('relative flex min-h-0 min-w-0 flex-1 w-full overflow-auto', className)} {...props}>
            <div className="absolute inset-0 min-h-0 min-w-0">{children}</div>
        </div>
    )
}
