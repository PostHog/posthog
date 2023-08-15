import { useState } from 'react'
import { LemonButton } from '../LemonButton'
import { IconUnfoldLess, IconUnfoldMore } from '../icons'
import './LemonWidget.scss'
import clsx from 'clsx'

export interface LemonWidgetProps {
    title: string
    children: React.ReactChild
}

export function LemonWidget({ title, children }: LemonWidgetProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState<boolean>(true)

    return (
        <Widget classNames="border">
            <Header>
                <LemonButton
                    onClick={() => setIsExpanded(!isExpanded)}
                    size="small"
                    status="primary-alt"
                    className="flex-1"
                    sideIcon={null}
                >
                    <span className="flex-1 cursor-pointer">{title}</span>
                </LemonButton>
                <LemonButton
                    onClick={() => setIsExpanded(!isExpanded)}
                    size="small"
                    icon={isExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                />
            </Header>
            {isExpanded && <Content>{children}</Content>}
        </Widget>
    )
}

const Widget = ({ children, classNames }: { children: React.ReactNode; classNames?: string }): JSX.Element => {
    return <div className={clsx('LemonWidget', classNames)}>{children}</div>
}

const Header = ({ children, classNames }: { children: React.ReactNode; classNames?: string }): JSX.Element => {
    return <div className={clsx('LemonWidget__header', classNames)}>{children}</div>
}

const Content = ({ children }: { children: React.ReactNode }): JSX.Element => {
    return <div className="px-2.5 py-2 border-t border-border">{children}</div>
}
