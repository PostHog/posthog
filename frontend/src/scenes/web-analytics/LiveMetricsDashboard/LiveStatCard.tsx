import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

const AnimatedNumber = ({ value, duration = 300 }: { value: number; duration?: number }): JSX.Element => {
    const [displayValue, setDisplayValue] = useState(value)
    const [isAnimating, setIsAnimating] = useState(false)
    const displayValueRef = useRef(value)
    const animationRef = useRef<number>()

    useEffect(() => {
        if (value === displayValueRef.current) {
            return
        }

        if (animationRef.current) {
            cancelAnimationFrame(animationRef.current)
        }

        const startValue = displayValueRef.current
        const endValue = value
        const startTime = performance.now()

        setIsAnimating(true)

        const animate = (currentTime: number): void => {
            const elapsed = currentTime - startTime
            const progress = Math.min(elapsed / duration, 1)

            const easeOut = 1 - (1 - progress) * (1 - progress)
            const currentValue = Math.round(startValue + (endValue - startValue) * easeOut)

            displayValueRef.current = currentValue
            setDisplayValue(currentValue)

            if (progress < 1) {
                animationRef.current = requestAnimationFrame(animate)
            } else {
                displayValueRef.current = endValue
                setDisplayValue(endValue)
                setIsAnimating(false)
            }
        }

        animationRef.current = requestAnimationFrame(animate)

        return () => {
            if (animationRef.current) {
                cancelAnimationFrame(animationRef.current)
            }
        }
    }, [value, duration])

    return (
        <span
            className={clsx(
                'text-2xl font-bold tabular-nums transition-colors duration-300',
                isAnimating && 'text-primary'
            )}
        >
            {displayValue.toLocaleString()}
        </span>
    )
}

export interface LiveStatCardProps {
    label: string
    value: number | null
    isLoading?: boolean
}

export const LiveStatCard = ({ label, value, isLoading }: LiveStatCardProps): JSX.Element => {
    return (
        <div className="flex flex-col">
            <span className="text-muted text-xs uppercase font-medium">{label}</span>
            {isLoading ? (
                <LemonSkeleton className="w-16 h-8 mt-1" />
            ) : (
                <div className="flex items-baseline">
                    {value !== null ? <AnimatedNumber value={value} /> : <span className="text-2xl font-bold">-</span>}
                </div>
            )}
        </div>
    )
}

export const LiveStatDivider = (): JSX.Element => <div className="w-px h-10 bg-border hidden md:block" />
