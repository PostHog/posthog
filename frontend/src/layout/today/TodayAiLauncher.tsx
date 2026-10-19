import { useEffect, useRef } from 'react'

import type { TodayAiLauncherVariant } from './todayContextPanelLogic'

const LOOK_X = 2
const LOOK_Y = 1.5
const LOOK_REACH = 240

interface TodayAiLauncherProps {
    variant: TodayAiLauncherVariant
    followPointer?: boolean
}

export function TodayAiLauncher({ variant, followPointer = false }: TodayAiLauncherProps): JSX.Element {
    const ref = useRef<HTMLSpanElement>(null)
    const hasEyes = variant === 'eyes' || variant === 'eyes-light'

    useEffect(() => {
        const element = ref.current
        if (!followPointer || !hasEyes || !element || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            return
        }
        let frame = 0
        let pointer = { x: 0, y: 0 }
        const look = (): void => {
            frame = 0
            const rect = element.getBoundingClientRect()
            const dx = pointer.x - (rect.left + rect.width / 2)
            const dy = pointer.y - (rect.top + rect.height / 2)
            const distance = Math.hypot(dx, dy) || 1
            const reach = Math.min(distance / LOOK_REACH, 1)
            element.style.setProperty('--launcher-look-x', `${((dx / distance) * reach * LOOK_X).toFixed(2)}px`)
            element.style.setProperty('--launcher-look-y', `${((dy / distance) * reach * LOOK_Y).toFixed(2)}px`)
        }
        const onPointerMove = (event: PointerEvent): void => {
            pointer = { x: event.clientX, y: event.clientY }
            frame ||= requestAnimationFrame(look)
        }
        window.addEventListener('pointermove', onPointerMove, { passive: true })
        return () => {
            window.removeEventListener('pointermove', onPointerMove)
            cancelAnimationFrame(frame)
        }
    }, [followPointer, hasEyes])

    return (
        <span ref={ref} className="TodayAiLauncher" data-variant={variant}>
            {hasEyes ? (
                <>
                    <span className="TodayAiLauncher__eyes">
                        <span className="TodayAiLauncher__eye" />
                        <span className="TodayAiLauncher__eye" />
                    </span>
                    <svg className="TodayAiLauncher__smile" viewBox="0 0 28 16" aria-hidden>
                        <path d="M6.4 9.6 Q9.4 4.8 12.4 9.6 M15.6 9.6 Q18.6 4.8 21.6 9.6" />
                    </svg>
                </>
            ) : (
                <span className="TodayAiLauncher__court">
                    <span className="TodayAiLauncher__paddle" />
                    <span className="TodayAiLauncher__ball" />
                    <span className="TodayAiLauncher__paddle" />
                </span>
            )}
        </span>
    )
}
