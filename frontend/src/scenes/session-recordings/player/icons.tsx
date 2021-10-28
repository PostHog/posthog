// Base icons from https://github.com/ant-design/ant-design

import React from 'react'
import { RedoOutlined, UndoOutlined } from '@ant-design/icons'

function BaseIcon({
    children,
    onClick = () => {},
    className = '',
}: {
    children: JSX.Element
    onClick?: () => void
    className?: string
}): JSX.Element {
    return (
        <div onClick={onClick} className={`rrweb-controller-icon ${className}`}>
            {children}
        </div>
    )
}

export function IconSeekBack({
    onClick,
    time,
}: {
    onClick: () => void
    time: number
    className?: string
}): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className="rrweb-controller-icon-seek">
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
}: {
    onClick: () => void
    time: number
    className?: string
}): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className="rrweb-controller-icon-seek">
            <>
                <span className="seek-seconds">{time}</span>
                <RedoOutlined className="seek-icon" rotate={270} />
            </>
        </BaseIcon>
    )
}

export function IconPlay({ onClick, className = '' }: { onClick?: () => void; className?: string }): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className={className}>
            <svg width="1em" height="1em" viewBox="0 0 13 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M0 16L12.4444 8L0 0V16Z" fill="currentcolor" />
            </svg>
        </BaseIcon>
    )
}

export function IconPause({ onClick, className = '' }: { onClick?: () => void; className?: string }): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className={className}>
            <svg width="1em" height="1em" viewBox="0 0 12 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M0 16H4V0H0V16ZM8 16H12V0H8V16Z" fill="currentcolor" />
            </svg>
        </BaseIcon>
    )
}

export function IconFullscreen({ onClick, className = '' }: { onClick: () => void; className?: string }): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className={className}>
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path
                    d="M9.06247 7.38754L10.4343 6.01567C10.4674 5.98246 10.4905 5.94064 10.5009 5.89498C10.5114 5.84931 10.5088 5.80163 10.4935 5.75735C10.4782 5.71307 10.4508 5.67397 10.4143 5.64451C10.3779 5.61504 10.334 5.59639 10.2875 5.59067L5.28122 5.00004C5.12184 4.98129 4.98434 5.11567 5.00309 5.27817L5.59372 10.2844C5.61872 10.4907 5.87184 10.5782 6.01872 10.4313L7.38434 9.06567L11.5625 13.2407C11.6593 13.3375 11.8187 13.3375 11.9156 13.2407L13.2406 11.9188C13.3375 11.8219 13.3375 11.6625 13.2406 11.5657L9.06247 7.38754ZM20.0843 13.2407C20.1812 13.3375 20.3406 13.3375 20.4375 13.2407L24.6156 9.06567L25.9812 10.4313C26.0144 10.4643 26.0562 10.4874 26.1019 10.4979C26.1476 10.5083 26.1953 10.5057 26.2395 10.4904C26.2838 10.4751 26.3229 10.4477 26.3524 10.4113C26.3818 10.3749 26.4005 10.3309 26.4062 10.2844L26.9968 5.28129C27.0156 5.12192 26.8812 4.98442 26.7187 5.00317L21.7125 5.59379C21.5062 5.61879 21.4187 5.87192 21.5656 6.01879L22.9375 7.39067L18.7593 11.5625C18.7128 11.6095 18.6867 11.673 18.6867 11.7391C18.6867 11.8052 18.7128 11.8687 18.7593 11.9157L20.0843 13.2407V13.2407ZM26.4062 21.7157C26.3812 21.5094 26.1281 21.4219 25.9812 21.5688L24.6156 22.9344L20.4375 18.7594C20.3905 18.7129 20.327 18.6868 20.2609 18.6868C20.1948 18.6868 20.1313 18.7129 20.0843 18.7594L18.7593 20.0813C18.7128 20.1283 18.6867 20.1917 18.6867 20.2579C18.6867 20.324 18.7128 20.3874 18.7593 20.4344L22.9375 24.6125L21.5656 25.9844C21.5325 26.0176 21.5095 26.0594 21.499 26.1051C21.4886 26.1508 21.4911 26.1985 21.5064 26.2427C21.5217 26.287 21.5492 26.3261 21.5856 26.3556C21.622 26.385 21.666 26.4037 21.7125 26.4094L26.7187 27C26.8781 27.0188 27.0156 26.8844 26.9968 26.7219L26.4062 21.7157ZM11.9156 18.7594C11.8686 18.7129 11.8052 18.6868 11.739 18.6868C11.6729 18.6868 11.6095 18.7129 11.5625 18.7594L7.38434 22.9344L6.01872 21.5688C5.98551 21.5357 5.9437 21.5127 5.89803 21.5022C5.85236 21.4918 5.80468 21.4943 5.7604 21.5096C5.71612 21.5249 5.67702 21.5524 5.64756 21.5888C5.61809 21.6252 5.59944 21.6692 5.59372 21.7157L5.00309 26.7188C4.98434 26.8782 5.11872 27.0157 5.28122 26.9969L10.2875 26.4063C10.4937 26.3813 10.5812 26.1282 10.4343 25.9813L9.06247 24.6125L13.2406 20.4375C13.3375 20.3407 13.3375 20.1813 13.2406 20.0844L11.9156 18.7594V18.7594Z"
                    fill="currentColor"
                />
            </svg>
        </BaseIcon>
    )
}

export function IconStepForward({ onClick, className = '' }: { onClick: () => void; className?: string }): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className={className}>
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path
                    d="M21.1375 16.5297L9.1625 25.9366C8.71719 26.2866 8.0625 25.9709 8.0625 25.4069V6.59281C8.0625 6.02875 8.71719 5.71344 9.1625 6.06344L21.1375 15.4703C21.2179 15.5333 21.2828 15.6137 21.3275 15.7054C21.3722 15.7972 21.3955 15.8979 21.3955 16C21.3955 16.1021 21.3722 16.2028 21.3275 16.2946C21.2828 16.3864 21.2179 16.4667 21.1375 16.5297V16.5297ZM21.6875 27H23.6875C23.7538 27 23.8174 26.9737 23.8643 26.9268C23.9112 26.8799 23.9375 26.8163 23.9375 26.75V5.25C23.9375 5.1837 23.9112 5.12011 23.8643 5.07322C23.8174 5.02634 23.7538 5 23.6875 5H21.6875C21.6212 5 21.5576 5.02634 21.5107 5.07322C21.4638 5.12011 21.4375 5.1837 21.4375 5.25V26.75C21.4375 26.8163 21.4638 26.8799 21.5107 26.9268C21.5576 26.9737 21.6212 27 21.6875 27Z"
                    fill="currentColor"
                />
            </svg>
        </BaseIcon>
    )
}

export function IconStepBackward({
    onClick,
    className = '',
}: {
    onClick: () => void
    className?: string
}): JSX.Element {
    return (
        <BaseIcon onClick={onClick} className={className}>
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path
                    d="M10.8625 16.5297L22.8375 25.9366C23.2828 26.2866 23.9375 25.9709 23.9375 25.4069V6.59281C23.9375 6.02875 23.2828 5.71344 22.8375 6.06344L10.8625 15.4703C10.7821 15.5333 10.7172 15.6137 10.6725 15.7054C10.6278 15.7972 10.6045 15.8979 10.6045 16C10.6045 16.1021 10.6278 16.2028 10.6725 16.2946C10.7172 16.3864 10.7821 16.4667 10.8625 16.5297V16.5297ZM10.3125 27H8.3125C8.2462 27 8.18261 26.9737 8.13572 26.9268C8.08884 26.8799 8.0625 26.8163 8.0625 26.75V5.25C8.0625 5.1837 8.08884 5.12011 8.13572 5.07322C8.18261 5.02634 8.2462 5 8.3125 5H10.3125C10.3788 5 10.4424 5.02634 10.4893 5.07322C10.5362 5.12011 10.5625 5.1837 10.5625 5.25V26.75C10.5625 26.8163 10.5362 26.8799 10.4893 26.9268C10.4424 26.9737 10.3788 27 10.3125 27Z"
                    fill="currentColor"
                />
            </svg>
        </BaseIcon>
    )
}
