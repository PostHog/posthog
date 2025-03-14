function WidgetHeader({ title, children }: { title: string; children?: React.ReactNode }): JSX.Element {
    return (
        <div className="flex justify-between items-center border-b-1 border-primary px-2 py-1 ">
            <span className="text-sm font-semibold">{title}</span>
            {children && <div className="flex">{children}</div>}
        </div>
    )
}

function WidgetBody({ children }: { children?: React.ReactNode }): JSX.Element {
    return <div className="p-2">{children}</div>
}

function WidgetRoot({ children }: { children?: React.ReactNode }): JSX.Element {
    return <div className="flex flex-col border-1 border-primary bg-surface-primary rounded">{children}</div>
}

export const Widget = {
    Header: WidgetHeader,
    Body: WidgetBody,
    Root: WidgetRoot,
}
