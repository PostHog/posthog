import React from 'react'
import './index.scss'

export function StarryBackground({
    children,
    style,
}: {
    children: JSX.Element
    style?: React.CSSProperties
}): JSX.Element {
    return (
        <div className="starry-background" style={style}>
            <div className="stars" />
            <div className="children">{children}</div>
        </div>
    )
}
