// Base icons from https://github.com/ant-design/ant-design

import React, { CSSProperties } from 'react'
import { RedoOutlined, UndoOutlined } from '@ant-design/icons'

function BaseIcon({
    children,
    onClick = () => {},
    className = '',
    style = {},
}: {
    children: JSX.Element
    onClick?: () => void
    className?: string
    style?: CSSProperties
}): JSX.Element {
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
    onClick: () => void
    time: number
    style?: CSSProperties
}): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className="rrweb-controller-icon-seek" style={style}>
            <>
                <span className="seek-seconds">{time}</span>
                <UndoOutlined className="seek-icon" rotate={90} />
            </>
        </BaseIcon>
    )
}

export function IconSeekForward({
    onClick,
    time,
    style,
}: {
    onClick: () => void
    time: number
    style?: CSSProperties
}): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className="rrweb-controller-icon-seek" style={style}>
            <>
                <span className="seek-seconds">{time}</span>
                <RedoOutlined className="seek-icon" rotate={270} />
            </>
        </BaseIcon>
    )
}

export function IconPlay({
    onClick,
    style,
    className = '',
}: {
    onClick?: () => void
    style?: CSSProperties
    className?: string
}): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className={className} style={style}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M6 20.291L18.4444 12.291L6 4.29102V20.291Z" fill="currentColor" />
            </svg>
        </BaseIcon>
    )
}

export function IconPause({
    onClick,
    style,
    className = '',
}: {
    onClick?: () => void
    style?: CSSProperties
    className?: string
}): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className={className} style={style}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path
                    d="M9 16H11V8H9V16ZM12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 20C7.59 20 4 16.41 4 12C4 7.59 7.59 4 12 4C16.41 4 20 7.59 20 12C20 16.41 16.41 20 12 20ZM13 16H15V8H13V16Z"
                    fill="currentColor"
                />
            </svg>
        </BaseIcon>
    )
}
