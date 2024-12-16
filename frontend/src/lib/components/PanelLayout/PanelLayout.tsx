import clsx from 'clsx'

type PanelContainerProps = {
    title: string
    children: React.ReactNode
    primary: boolean
    className?: string
    column?: boolean
}

function PanelLayout({ className, ...props }: Omit<PanelContainerProps, 'primary' | 'title'>): JSX.Element {
    return <Container className={clsx(className, 'PanelLayout')} {...props} primary={false} />
}

function Container({ children, primary, className, column }: Omit<PanelContainerProps, 'title'>): JSX.Element {
    return (
        <div
            className={clsx(
                'flex',
                primary && 'flex-1',
                column ? 'flex-col gap-y-2' : 'gap-x-2',
                primary ? 'PanelLayout__container--primary' : 'PanelLayout__container--secondary',
                className
            )}
        >
            {children}
        </div>
    )
}

function Panel({ children, title, primary, className }: Omit<PanelContainerProps, 'column'>): JSX.Element {
    return (
        <div className={clsx(primary && 'flex-1', 'border bg-bg-light rounded-sm', className)}>
            <div className="border-b px-1 flex justify-between">
                <span>{title}</span>
            </div>
            {children}
        </div>
    )
}

PanelLayout.Panel = Panel
PanelLayout.Container = Container

export default PanelLayout
