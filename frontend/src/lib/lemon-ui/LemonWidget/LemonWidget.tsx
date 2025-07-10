import './LemonWidget.scss'

import clsx from 'clsx'

import { IconX } from '@posthog/icons'

import { LemonButton } from '../LemonButton'

export interface LemonWidgetProps {
    title: string
    onClose?: () => void
    actions?: React.ReactNode
    children: React.ReactNode
    className?: string
}

export function LemonWidget({ title, onClose, actions, children, className }: LemonWidgetProps): JSX.Element {
    return (
        <Widget className={className}>
            <Header>
                <span className="text-primary-alt flex-1 truncate px-2">{title}</span>
                {actions}

                {onClose && <LemonButton status="danger" onClick={onClose} size="small" icon={<IconX />} />}
            </Header>
            <Content>{children}</Content>
        </Widget>
    )
}

const Widget = ({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element => {
    return <div className={clsx('LemonWidget', className)}>{children}</div>
}

const Header = ({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element => {
    return <div className={clsx('LemonWidget__header', className)}>{children}</div>
}

const Content = ({ children }: { children: React.ReactNode }): JSX.Element => {
    return <div className="LemonWidget__content border-primary border-t">{children}</div>
}
