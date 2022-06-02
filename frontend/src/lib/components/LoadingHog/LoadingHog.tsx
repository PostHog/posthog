import './LoadingHog.scss'
import laptophog from 'public/animations/laptophog.json'
import { Player } from '@lottiefiles/react-lottie-player'
import React, { useEffect, useState } from 'react'
import clsx from 'clsx'

interface LoadingHogProps {
    className?: string
    style?: React.CSSProperties
}

export function LoadingHog({ className, style }: LoadingHogProps): JSX.Element {
    // Delay 300ms before showing LoadingHog, to not confuse users with subliminal hedgehogs
    // that flash before their eyes. Then take 400ms to fade in the animation.
    const [visible, setVisible] = useState(false)
    useEffect(() => {
        const timeout = window.setTimeout(() => setVisible(true), 300)
        return () => window.clearTimeout(timeout)
    }, [])
    return (
        <Player
            autoplay
            loop
            src={laptophog}
            className={clsx('LoadingHog', { LoadingHog__hidden: !visible }, className)}
            style={style}
        />
    )
}
