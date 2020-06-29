import './Fade.scss'
import React, { useEffect, useState } from 'react'

export function Fade({ visible, children, ...props }) {
    const [shouldRender, setShouldRender] = useState(visible)

    useEffect(() => {
        if (visible) {
            setShouldRender(true)
        }
    }, [visible])

    const onAnimationEnd = () => {
        if (!visible) {
            setShouldRender(false)
        }
    }

    return shouldRender ? (
        <div
            style={{ animation: `${visible ? 'fadeComponentFadeIn' : 'fadeComponentFadeOut'} 0.3s` }}
            onAnimationEnd={onAnimationEnd}
            {...props}
        >
            {children}
        </div>
    ) : null
}
