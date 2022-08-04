// Base icons from https://github.com/ant-design/ant-design

import React, { CSSProperties } from 'react'
import { RedoOutlined, UndoOutlined } from '@ant-design/icons'
import clsx from 'clsx'
import { LemonButton } from 'lib/components/LemonButton'

interface IconProps {
    onClick?: () => void
    style?: CSSProperties
    className?: string
}
function BaseIcon({
    children,
    onClick = () => {},
    className = '',
    style = {},
}: {
    children: JSX.Element
} & IconProps): JSX.Element {
    return (
        <div onClick={onClick} className={`rrweb-controller-icon ${className}`} style={style}>
            {children}
        </div>
    )
}

export function IconSeekBack({
    onClick,
    time,
    style,
}: {
    time: number
} & IconProps): JSX.Element {
    return (
        <BaseIcon onClick={onClick} style={style}>
            <LemonButton status="primary-alt" size="small">
                <div className="rrweb-controller-icon-seek">
                    <span className="seek-seconds">{time}</span>
                    <UndoOutlined className="seek-icon" rotate={90} />
                </div>
            </LemonButton>
        </BaseIcon>
    )
}

export function IconSeekForward({
    onClick,
    time,
    style,
}: {
    time: number
} & IconProps): JSX.Element {
    return (
        <BaseIcon onClick={onClick} style={style}>
            <LemonButton status="primary-alt" size="small">
                <div className="rrweb-controller-icon-seek">
                    <span className="seek-seconds">{time}</span>
                    <RedoOutlined className="seek-icon" rotate={270} />
                </div>
            </LemonButton>
        </BaseIcon>
    )
}

export function IconPlay({ onClick, style, className = '' }: IconProps): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className={className} style={style}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M6 20.291L18.4444 12.291L6 4.29102V20.291Z" fill="currentColor" />
            </svg>
        </BaseIcon>
    )
}

export function IconPause({ onClick, style, className = '' }: IconProps): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className={className} style={style}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M6 19H10V5H6V19ZM14 5V19H18V5H14Z" fill="currentColor" />
            </svg>
        </BaseIcon>
    )
}

export function IconWindow({
    onClick,
    style,
    windowNumber,
    className = '',
}: { windowNumber: number } & IconProps): JSX.Element {
    return (
        <div onClick={onClick} className={clsx('icon-window', className)} style={style}>
            <span className="icon-window-number">{windowNumber}</span>
            <svg
                className="icon-window-icon"
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
            >
                <path
                    d="M19 4H5C3.89 4 3 4.9 3 6V18C3 19.1 3.89 20 5 20H19C20.1 20 21 19.1 21 18V6C21 4.9 20.11 4 19 4ZM19 18H5V8H19V18Z"
                    fill="currentColor"
                />
            </svg>
        </div>
    )
}
