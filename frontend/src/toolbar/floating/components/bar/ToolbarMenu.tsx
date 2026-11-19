import clsx from 'clsx'

export type ToolbarMenuProps = {
    children: React.ReactNode
    className?: string
}

export function ToolbarMenu({ children, className }: ToolbarMenuProps): JSX.Element {
    return <div className={clsx('w-full h-full flex flex-col overflow-hidden', className)}>{children}</div>
}

ToolbarMenu.Header = function ToolbarMenuHeader({ children, className }: ToolbarMenuProps): JSX.Element {
    return <div className={clsx('px-2 pt-1', className)}>{children}</div>
}

ToolbarMenu.Body = function ToolbarMenuBody({ children, className }: ToolbarMenuProps): JSX.Element {
    return (
        <div className={clsx('flex flex-col flex-1 h-full overflow-y-auto min-h-20 px-2 py-1', className)}>
            {children}
        </div>
    )
}

ToolbarMenu.Footer = function ToolbarMenuFooter({ children, className }: ToolbarMenuProps): JSX.Element {
    return <div className={clsx('flex flex-row items-center border-t gap-2 px-2 py-1', className)}>{children}</div>
}
