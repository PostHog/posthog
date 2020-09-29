import './Fade.scss'
import React, { useEffect, useState } from 'react'

export function Fade({
    visible,
    children,
    style = {},
    ...props
}: {
    visible: boolean
    children: React.ReactNode
    style?: React.CSSProperties
}): JSX.Element | null {
    const [shouldRender, setShouldRender] = useState(visible)

    useEffect(() => {
        if (visible) {
            setShouldRender(true)
        }
    }, [visible])

    const onAnimationEnd = (): void => {
        if (!visible) {
            setShouldRender(false)
        }
    }

    return shouldRender ? (
        <div
            className="fade-component-container"
            style={{ animation: `${visible ? 'fadeComponentFadeIn' : 'fadeComponentFadeOut'} 0.3s`, ...style }}
            onAnimationEnd={onAnimationEnd}
            {...props}
        >
            {children}
        </div>
    ) : null
}
