import { useEffect, useRef } from 'react'

import type { TodayAiLauncherVariant } from './todayContextPanelLogic'

const LOOK_X = 2
const LOOK_Y = 1.5
const LOOK_REACH = 240
const WAKE_NEAR = 60
const WAKE_FAR = 420

const smile = (centers: number[], cy = 17, width = 3.2): string =>
    centers.map((x) => `M${x - width} ${cy + 1.6} Q${x} ${cy - 3.6} ${x + width} ${cy + 1.6}`).join(' ')

interface TodayAiLauncherProps {
    variant: TodayAiLauncherVariant
    followPointer?: boolean
}

export function TodayAiLauncher({ variant, followPointer = false }: TodayAiLauncherProps): JSX.Element {
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
        <span ref={ref} className="TodayAiLauncher" data-variant={variant}>
            <svg className="TodayAiLauncher__art" viewBox="0 0 64 32" aria-hidden>
                {variant === 'eyes' && (
                    <>
                        <g className="TodayAiLauncher__eyes">
                            <ellipse className="TodayAiLauncher__blink" cx="27.4" cy="16" rx="3.5" ry="5.2" />
                            <ellipse className="TodayAiLauncher__blink" cx="36.6" cy="16" rx="3.5" ry="5.2" />
                        </g>
                        <path className="TodayAiLauncher__smile" d={smile([27.4, 36.6])} />
                    </>
                )}
                {variant === 'pupils' && (
                    <>
                        <g className="TodayAiLauncher__eyes">
                            {[27, 37].map((cx) => (
                                <g key={cx} className="TodayAiLauncher__blink">
                                    <ellipse cx={cx} cy="16" rx="4.2" ry="5.5" />
                                    <circle className="TodayAiLauncher__pupil" cx={cx} cy="16" r="2.4" />
                                </g>
                            ))}
                        </g>
                        <path className="TodayAiLauncher__smile" d={smile([27, 37])} />
                        <g className="TodayAiLauncher__blush">
                            <ellipse cx="22.4" cy="21.8" rx="2.6" ry="1.4" />
                            <ellipse cx="41.6" cy="21.8" rx="2.6" ry="1.4" />
                        </g>
                    </>
                )}
                {variant === 'sleepy' && (
                    <>
                        <g className="TodayAiLauncher__eyes">
                            <ellipse className="TodayAiLauncher__lid" cx="27.4" cy="16" rx="3.5" ry="5.2" />
                            <ellipse className="TodayAiLauncher__lid" cx="36.6" cy="16" rx="3.5" ry="5.2" />
                        </g>
                        <path className="TodayAiLauncher__smile" d={smile([27.4, 36.6])} />
                    </>
                )}
                {variant === 'glasses' && (
                    <>
                        <g className="TodayAiLauncher__frames">
                            <circle cx="25" cy="16" r="6.2" />
                            <circle cx="39" cy="16" r="6.2" />
                            <path d="M31.2 15 Q32 13.4 32.8 15 M18.8 15 L16 13.2 M45.2 15 L48 13.2" />
                        </g>
                        <g className="TodayAiLauncher__eyes">
                            <ellipse className="TodayAiLauncher__blink" cx="25" cy="16" rx="2.3" ry="3.2" />
                            <ellipse className="TodayAiLauncher__blink" cx="39" cy="16" rx="2.3" ry="3.2" />
                        </g>
                        <path className="TodayAiLauncher__smile" d={smile([25, 39], 16.6, 2.6)} />
                    </>
                )}
                {variant === 'peek' && (
                    <g className="TodayAiLauncher__head">
                        <path className="TodayAiLauncher__skin" d="M20.5 2 C20.5 -11.5 43.5 -11.5 43.5 2 Z" />
                        <g className="TodayAiLauncher__eyes">
                            <ellipse className="TodayAiLauncher__blink" cx="28" cy="-4" rx="2.3" ry="3.3" />
                            <ellipse className="TodayAiLauncher__blink" cx="36" cy="-4" rx="2.3" ry="3.3" />
                        </g>
                        <path className="TodayAiLauncher__smile" d={smile([28, 36], -4.6, 2.2)} />
                        <rect className="TodayAiLauncher__skin" x="17.4" y="-1.4" width="6" height="3.6" rx="1.8" />
                        <rect className="TodayAiLauncher__skin" x="40.6" y="-1.4" width="6" height="3.6" rx="1.8" />
                    </g>
                )}
            </svg>
        </span>
    )
}
