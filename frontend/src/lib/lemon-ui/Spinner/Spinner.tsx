import './Spinner.scss'

import posthog from 'posthog-js'
import { useEffect, useId, useRef } from 'react'
import { twJoin, twMerge } from 'tailwind-merge'

import { IconPencil } from '@posthog/icons'

import { useCancelAnimationsOnUnmount } from 'lib/hooks/useCancelAnimationsOnUnmount'

function useTimingCapture(captureTime: boolean): void {
    const mountTimeRef = useRef<number>(performance.now())

    useEffect(() => {
        if (!captureTime) {
            return
        }

        const mountTime = mountTimeRef.current
        return () => {
            const visibleTimeMs = performance.now() - mountTime
            if (visibleTimeMs < 100) {
                return // Don't bother capturing really short loads
            }
            posthog.capture('spinner_unloaded', {
                visible_time_ms: visibleTimeMs,
            })
        }
    }, [captureTime])
}

export interface SpinnerProps {
    textColored?: boolean
    className?: string
    speed?: `${number}s` // Seconds
    captureTime?: boolean
    size?: 'small' | 'medium' | 'large'
    frozen?: boolean
}

/** Smoothly animated spinner for loading states. It does not indicate progress, only that something's happening. */
export function Spinner({
    textColored = false,
    className,
    speed = '1s',
    captureTime = false,
    size = 'small',
    frozen = false,
}: SpinnerProps): JSX.Element {
    useTimingCapture(captureTime)
    const ref = useCancelAnimationsOnUnmount<SVGSVGElement>()

    return (
        <svg
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--spinner-speed': speed } as React.CSSProperties}
            className={twMerge(
                'LemonIcon Spinner',
                textColored && `Spinner--textColored`,
                size && `Spinner--${size}`,
                frozen && 'Spinner--frozen',
                className
            )}
            viewBox="0 0 48 48"
            xmlns="http://www.w3.org/2000/svg"
        >
            <g className="Spinner__layer">
                <circle cx="24" cy="24" r="16" />
            </g>
            <g className="Spinner__layer">
                <circle cx="24" cy="24" r="16" />
            </g>
        </svg>
    )
}

export function SpinnerOverlay({
    sceneLevel,
    visible = true,
    className,
    mode = 'spinning',
    ...spinnerProps
}: SpinnerProps & {
    /** @default false */
    sceneLevel?: boolean
    /** @default true */
    visible?: boolean
    /** @default "spinning" */
    mode?: 'spinning' | 'editing'
}): JSX.Element {
    const ref = useCancelAnimationsOnUnmount<HTMLDivElement>()
    const effectId = useId()
    const isSceneLoading = sceneLevel && mode === 'spinning'

    return (
        <div
            ref={ref}
            className={twJoin(
                'SpinnerOverlay',
                sceneLevel && 'SpinnerOverlay--scene-level',
                isSceneLoading && 'SpinnerOverlay--thinking',
                spinnerProps.frozen && 'SpinnerOverlay--frozen'
            )}
            aria-hidden={!visible}
            role={isSceneLoading ? 'status' : undefined}
            aria-label={isSceneLoading ? 'Loading' : undefined}
        >
            {isSceneLoading && (
                <>
                    <svg
                        className="SpinnerOverlay__ribbon"
                        viewBox="0 0 1000 600"
                        preserveAspectRatio="none"
                        aria-hidden
                    >
                        <defs>
                            <filter id={effectId} x="-30%" y="-50%" width="160%" height="200%">
                                <feGaussianBlur stdDeviation={18} />
                            </filter>
                            <path
                                id={`${effectId}-secondary`}
                                pathLength={100}
                                d="M-100 420C120 50 820 20 800 300C780 560 220 550 250 290C280 60 690 150 620 330C560 490 360 370 460 260C570 160 840 420 1100 180"
                            />
                            <path
                                id={`${effectId}-accent`}
                                pathLength={100}
                                d="M-100 160C180 540 900 530 850 220C800-60 140 70 180 350C220 600 720 500 700 270C680 60 390 190 450 340C510 480 830 80 1100 340"
                            />
                        </defs>
                        <use
                            href={`#${effectId}-secondary`}
                            className="SpinnerOverlay__haze"
                            filter={`url(#${effectId})`}
                        />
                        <use href={`#${effectId}-secondary`} className="SpinnerOverlay__trace" />
                        <use
                            href={`#${effectId}-secondary`}
                            className="SpinnerOverlay__pulse SpinnerOverlay__pulse--tail-far"
                        />
                        <use
                            href={`#${effectId}-secondary`}
                            className="SpinnerOverlay__pulse SpinnerOverlay__pulse--tail-middle"
                        />
                        <use
                            href={`#${effectId}-secondary`}
                            className="SpinnerOverlay__pulse SpinnerOverlay__pulse--tail-near"
                        />
                        <use
                            href={`#${effectId}-secondary`}
                            className="SpinnerOverlay__pulse SpinnerOverlay__pulse--glow"
                            filter={`url(#${effectId})`}
                        />
                        <use
                            href={`#${effectId}-secondary`}
                            className="SpinnerOverlay__pulse SpinnerOverlay__pulse--head"
                        />
                    </svg>
                    <svg
                        className="SpinnerOverlay__ribbon SpinnerOverlay__ribbon--accent"
                        viewBox="0 0 1000 600"
                        preserveAspectRatio="none"
                        aria-hidden
                    >
                        <use
                            href={`#${effectId}-accent`}
                            className="SpinnerOverlay__haze"
                            filter={`url(#${effectId})`}
                        />
                        <use href={`#${effectId}-accent`} className="SpinnerOverlay__trace" />
                        <use
                            href={`#${effectId}-accent`}
                            className="SpinnerOverlay__pulse SpinnerOverlay__pulse--tail-far"
                        />
                        <use
                            href={`#${effectId}-accent`}
                            className="SpinnerOverlay__pulse SpinnerOverlay__pulse--tail-middle"
                        />
                        <use
                            href={`#${effectId}-accent`}
                            className="SpinnerOverlay__pulse SpinnerOverlay__pulse--tail-near"
                        />
                        <use
                            href={`#${effectId}-accent`}
                            className="SpinnerOverlay__pulse SpinnerOverlay__pulse--glow"
                            filter={`url(#${effectId})`}
                        />
                        <use
                            href={`#${effectId}-accent`}
                            className="SpinnerOverlay__pulse SpinnerOverlay__pulse--head"
                        />
                    </svg>
                </>
            )}
            {mode === 'editing' ? (
                <IconPencil className="text-5xl text-accent z-10 drop-shadow-xl" />
            ) : (
                <Spinner className={twMerge('text-5xl', className)} {...spinnerProps} />
            )}
        </div>
    )
}
