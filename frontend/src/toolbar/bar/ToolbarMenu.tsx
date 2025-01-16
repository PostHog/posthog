import clsx from 'clsx'

export type ToolbarMenuProps = {
    children: React.ReactNode
    className?: string
    noPadding?: boolean
}

export function ToolbarMenu({ children, className }: ToolbarMenuProps): JSX.Element {
    return <div className={clsx('w-full h-full flex flex-col overflow-hidden', className)}>{children}</div>
}

ToolbarMenu.Header = function ToolbarMenuHeader({ children, className, noPadding }: ToolbarMenuProps): JSX.Element {
    return <div className={clsx(!noPadding && 'px-1 pt-1', className)}>{children}</div>
}

ToolbarMenu.Body = function ToolbarMenuBody({ children, className, noPadding }: ToolbarMenuProps): JSX.Element {
    return (
        <div className={clsx(!noPadding && 'px-1', 'flex flex-col flex-1 h-full overflow-y-auto min-h-20', className)}>
            {children}
        </div>
    )
}

ToolbarMenu.Footer = function ToolbarMenufooter({ children, className, noPadding }: ToolbarMenuProps): JSX.Element {
    return (
        <div className={clsx(!noPadding && 'p-1', 'flex flex-row items-center border-t gap-2', className)}>
            {children}
        </div>
    )
}
