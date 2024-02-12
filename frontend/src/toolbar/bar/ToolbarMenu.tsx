export function ToolbarMenu({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="w-full h-full flex flex-col overflow-hidden">{children}</div>
}

ToolbarMenu.Header = function ToolbarMenuHeader({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="pt-1 px-1">{children}</div>
}

ToolbarMenu.Body = function ToolbarMenuBody({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="flex flex-col flex-1 h-full overflow-y-auto px-1 min-h-20">{children}</div>
}

ToolbarMenu.Footer = function ToolbarMenufooter({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="flex flex-row items-center p-2 border-t">{children}</div>
}
