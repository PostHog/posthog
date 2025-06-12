import { cn } from 'lib/utils/css-classes'
import { HTMLProps } from 'react'

export interface TabsSubHeaderProps extends HTMLProps<HTMLDivElement> {}

export function TabsSubHeader({ children, className }: TabsSubHeaderProps): JSX.Element {
    return <div className={cn('tabs-sub-header border-b-1 bg-surface-secondary px-2 py-1', className)}>{children}</div>
}
