import clsx from 'clsx'

type PanelContainerProps = {
    children: React.ReactNode
    primary: boolean
    className?: string
}

function PanelLayout(props: Omit<PanelContainerProps, 'primary'>): JSX.Element {
    return <Container {...props} primary={false} />
}

function Container({ children, primary, className }: PanelContainerProps): JSX.Element {
    return <div className={clsx('flex flex-wrap gap-2', primary && 'flex-1', className)}>{children}</div>
}

function Panel({ children, primary, className }: PanelContainerProps): JSX.Element {
    return <div className={clsx(primary && 'flex-1', 'border', className)}>{children}</div>
}

PanelLayout.Panel = Panel
PanelLayout.Container = Container

export default PanelLayout
