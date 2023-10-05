import { LemonButton } from '../LemonButton'
import { IconClose } from '../icons'
import './LemonWidget.scss'
import clsx from 'clsx'

export interface LemonWidgetProps {
    title: string
    onClose?: () => void
    scrollable?: boolean
    actions?: React.ReactNode
    children: React.ReactChild
}

export function LemonWidget({ title, onClose, scrollable = false, actions, children }: LemonWidgetProps): JSX.Element {
    return (
        <Widget className={scrollable ? 'flex flex-col overflow-auto' : ''}>
            <Header>
                <span className="flex-1 text-primary-alt px-2">{title}</span>
                {actions}

                {onClose && <LemonButton status="danger" onClick={onClose} size="small" icon={<IconClose />} />}
            </Header>
            {children}
        </Widget>
    )
}

const Widget = ({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element => {
    return <div className={clsx('LemonWidget', className)}>{children}</div>
}

const Header = ({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element => {
    return <div className={clsx('LemonWidget__header border-b border-border', className)}>{children}</div>
}
