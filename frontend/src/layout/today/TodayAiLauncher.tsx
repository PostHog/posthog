import { useEffect, useRef } from 'react'

const LOOK_X = 2
const LOOK_Y = 1.5
const LOOK_REACH = 240
const WAKE_NEAR = 60
const WAKE_FAR = 420
const EYES = [27.4, 36.6]

interface TodayAiLauncherProps {
    followPointer?: boolean
}

export function TodayAiLauncher({ followPointer = false }: TodayAiLauncherProps): JSX.Element {
    const ref = useRef<HTMLSpanElement>(null)

    useEffect(() => {
        const element = ref.current
        if (!followPointer || !element || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
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
            const near = 1 - Math.min(Math.max((distance - WAKE_NEAR) / (WAKE_FAR - WAKE_NEAR), 0), 1)
            element.style.setProperty('--launcher-look-x', `${((dx / distance) * reach * LOOK_X).toFixed(2)}px`)
            element.style.setProperty('--launcher-look-y', `${((dy / distance) * reach * LOOK_Y).toFixed(2)}px`)
            element.style.setProperty('--launcher-near', near.toFixed(2))
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
    }, [followPointer])

    return (
        <span ref={ref} className="TodayAiLauncher">
            <svg className="TodayAiLauncher__art" viewBox="0 0 64 32" aria-hidden>
                <g className="TodayAiLauncher__eyes">
                    {EYES.map((cx) => (
                        <ellipse key={cx} className="TodayAiLauncher__lid" cx={cx} cy="16" rx="3.5" ry="5.2" />
                    ))}
                </g>
                <path
                    className="TodayAiLauncher__smile"
                    d={EYES.map((x) => `M${x - 3.2} 18.6 Q${x} 13.4 ${x + 3.2} 18.6`).join(' ')}
                />
            </svg>
        </span>
    )
}
