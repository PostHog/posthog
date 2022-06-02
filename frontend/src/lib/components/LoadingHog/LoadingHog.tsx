import './LoadingHog.scss'
import laptophog from 'public/animations/laptophog.json'
import { Player } from '@lottiefiles/react-lottie-player'
import React, { useEffect, useState } from 'react'

interface LoadingHogProps {
    style?: React.CSSProperties
}

export function LoadingHog({ style }: LoadingHogProps): JSX.Element {
    const [showing, setShowing] = useState(false)
    useEffect(() => {
        const timeout = window.setTimeout(() => {
            setShowing(true)
        }, 300)
        return () => window.clearTimeout(timeout)
    }, [])
    return (
        <Player
            autoplay
            loop
            src={laptophog}
            className="LoadingHog"
            style={{
                opacity: showing ? 1 : 0,
                ...style,
            }}
        />
    )
}
