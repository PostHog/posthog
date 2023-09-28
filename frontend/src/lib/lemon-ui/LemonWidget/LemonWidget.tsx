import { useState } from 'react'
import { LemonButton } from '../LemonButton'
import { IconClose, IconUnfoldLess, IconUnfoldMore } from '../icons'
import './LemonWidget.scss'
import clsx from 'clsx'

export interface LemonWidgetProps {
    title: string
    collapsible?: boolean
    onClose?: () => void
    actions?: React.ReactNode
    children: React.ReactChild
}

export function LemonWidget({ title, collapsible = true, onClose, actions, children }: LemonWidgetProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState<boolean>(true)

    return (
        <Widget>
            <Header>
                {collapsible ? (
                    <>
                        <LemonButton
                            onClick={() => setIsExpanded(!isExpanded)}
                            size="small"
                            status="primary-alt"
                            className="flex-1"
                        >
                            <span className="flex-1 cursor-pointer">{title}</span>
                        </LemonButton>
                        <LemonButton
                            onClick={() => setIsExpanded(!isExpanded)}
                            size="small"
                            icon={isExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                        />
                    </>
                ) : (
                    <span className="flex-1 text-primary-alt px-2">{title}</span>
                )}
                {actions}

                {onClose && <LemonButton status="danger" onClick={onClose} size="small" icon={<IconClose />} />}
            </Header>
            {isExpanded && <Content>{children}</Content>}
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
    return <div className="border-t border-border">{children}</div>
}
