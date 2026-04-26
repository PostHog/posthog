import { useEffect, useState } from 'react'

export interface ExitTransitionState {
    mounted: boolean
    visible: boolean
}

export function useExitTransition(isIn: boolean, durationMs: number): ExitTransitionState {
    const [mounted, setMounted] = useState(isIn)
    const [visible, setVisible] = useState(isIn)

    useEffect(() => {
        if (isIn) {
            setMounted(true)
            const raf = window.requestAnimationFrame(() => setVisible(true))
            return () => window.cancelAnimationFrame(raf)
        }
        setVisible(false)
        const timer = window.setTimeout(() => setMounted(false), durationMs)
        return () => window.clearTimeout(timer)
    }, [isIn, durationMs])

    return { mounted, visible }
}
