import React from 'react'
import './LemonButton.scss'

export interface LemonButtonProps {
    children: React.ReactElement | string
    icon: React.ReactElement
    onClick: () => void
    style?: React.CSSProperties
}

export function LemonButton({ children, icon, onClick, style }: LemonButtonProps): JSX.Element {
    return (
        <button className="LemonButton" type="button" onClick={onClick} style={style}>
            <span className="LemonButton__icon">{icon}</span>
            {children}
        </button>
    )
}
