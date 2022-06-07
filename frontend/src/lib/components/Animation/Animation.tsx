import './Animation.scss'
import { Player } from '@lottiefiles/react-lottie-player'
import React, { useEffect, useState } from 'react'
import clsx from 'clsx'
import { AnimationType, getAnimationSource, animations } from 'lib/animations/animations'
import { Spinner } from 'lib/components/Spinner/Spinner'

export interface AnimationProps {
    /** Animation to show */
    type?: AnimationType
    /** Milliseconds to wait before showing the animation. Can be 0, defaults to 300. */
    delay?: number
    className?: string
    style?: React.CSSProperties
}

export function Animation({
    className,
    style,
    delay = 300,
    type = AnimationType.LaptopHog,
}: AnimationProps): JSX.Element {
    const [visible, setVisible] = useState(delay === 0)
    const [source, setSource] = useState<null | Record<string, any>>(null)
    const [showFallbackSpinner, setShowFallbackSpinner] = useState(false)
    const { width, height } = animations[type]

    // Delay 300ms before showing Animation, to not confuse users with subliminal hedgehogs
    // that flash before their eyes. Then take 400ms to fade in the animation.
    useEffect(() => {
        if (delay) {
            const timeout = window.setTimeout(() => setVisible(true), delay)
            return () => window.clearTimeout(timeout)
        }
    }, [delay])

    // Actually fetch the animation. Uses a cache to avoid multiple requests for the same file.
    // Show a fallback spinner if failed to fetch.
    useEffect(() => {
        let unmounted = false
        async function loadAnimation(): Promise<void> {
            try {
                const source = await getAnimationSource(type)
                !unmounted && setSource(source)
            } catch (e) {
                !unmounted && setShowFallbackSpinner(true)
            }
        }
        loadAnimation()
        return () => {
            unmounted = true
        }
    }, [type])

    return (
        <div
            className={clsx(
                'Animation',
                { 'Animation--hidden': !(visible && (source || showFallbackSpinner)) },
                className
            )}
            style={{ aspectRatio: `${width} / ${height}`, ...style }}
        >
            {source ? (
                <Player className="Animation__player" autoplay loop src={source} />
            ) : showFallbackSpinner ? (
                <Spinner />
            ) : null}
        </div>
    )
}
