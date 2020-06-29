import React, { useEffect, useState } from 'react'

export function Fade({ show, children, ...props }) {
    const [shouldRender, setRender] = useState(show)

    useEffect(() => {
        if (show) setRender(true)
    }, [show])

    const onAnimationEnd = () => {
        if (!show) setRender(false)
    }

    return shouldRender ? (
        <div style={{ animation: `${show ? 'fadeIn' : 'fadeOut'} 0.3s` }} onAnimationEnd={onAnimationEnd} {...props}>
            {children}
        </div>
    ) : null
}
