import { useState } from 'react'
import { Popover } from '../Popover'
import { LemonButton } from '../LemonButton'
import { IconUnfoldLess, IconUnfoldMore } from '../icons'
import './LemonWidget.scss'
import clsx from 'clsx'

export interface LemonWidgetProps {
    title: string
    icon: JSX.Element
    collapsed?: boolean
    selected?: boolean
    children: React.ReactChild
}

export function LemonWidget({
    title,
    icon,
    collapsed = false,
    selected = false,
    children,
}: LemonWidgetProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState<boolean>(true)
    const [visible, setVisible] = useState<boolean>(false)

    return collapsed ? (
        <Popover
            visible={visible}
            placement="right-start"
            className="LemonWidget__popover"
            onClickOutside={() => setVisible(false)}
            overlay={
                <Widget>
                    <Header>
                        <span>{title}</span>
                    </Header>
                    <Content>{children}</Content>
                </Widget>
            }
        >
            <LemonButton
                onClick={() => setVisible(!visible)}
                size="small"
                status="primary-alt"
                className="flex-1"
                icon={icon}
                type="secondary"
            />
        </Popover>
    ) : (
        <Widget classNames={clsx(selected && 'LemonWidget--selected', 'border')}>
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
