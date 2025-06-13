import { cn } from 'lib/utils/css-classes'
import { HTMLProps } from 'react'

export interface TabsHeaderProps extends HTMLProps<HTMLDivElement> {}

export function TabsHeader({ className, children }: TabsHeaderProps): JSX.Element {
    return <div className={cn('flex justify-between items-center h-[2rem] border-b-1 px-2', className)}>{children}</div>
}
