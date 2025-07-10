import clsx from 'clsx'

export type ToolbarMenuProps = {
    children: React.ReactNode
    className?: string
}

export function ToolbarMenu({ children, className }: ToolbarMenuProps): JSX.Element {
    return <div className={clsx('flex h-full w-full flex-col overflow-hidden', className)}>{children}</div>
}

ToolbarMenu.Header = function ToolbarMenuHeader({ children, className }: ToolbarMenuProps): JSX.Element {
    return <div className={clsx('px-2 pt-1', className)}>{children}</div>
}

ToolbarMenu.Body = function ToolbarMenuBody({ children, className }: ToolbarMenuProps): JSX.Element {
    return (
        <div className={clsx('flex h-full min-h-20 flex-1 flex-col overflow-y-auto px-2 py-1', className)}>
            {children}
        </div>
    )
}

ToolbarMenu.Footer = function ToolbarMenuFooter({ children, className }: ToolbarMenuProps): JSX.Element {
    return <div className={clsx('flex flex-row items-center gap-2 border-t px-2 py-1', className)}>{children}</div>
}
