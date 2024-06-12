import clsx from 'clsx'

export type ToolbarMenuProps = {
    children: React.ReactNode
    className?: string
}

export function ToolbarMenu({ children, className }: ToolbarMenuProps): JSX.Element {
    return <div className={clsx('w-full h-full flex flex-col overflow-hidden', className)}>{children}</div>
}

ToolbarMenu.Header = function ToolbarMenuHeader({ children, className }: ToolbarMenuProps): JSX.Element {
    return <div className={clsx('pt-1 px-1', className)}>{children}</div>
}

ToolbarMenu.Body = function ToolbarMenuBody({ children, className }: ToolbarMenuProps): JSX.Element {
    return (
        <div className={clsx('flex flex-col flex-1 h-full overflow-y-auto px-1 min-h-20', className)}>{children}</div>
    )
}

ToolbarMenu.Footer = function ToolbarMenufooter({ children, className }: ToolbarMenuProps): JSX.Element {
    return <div className={clsx('flex flex-row items-center p-2 border-t gap-2', className)}>{children}</div>
}
