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
                                d="M-100 460C80 200 400 160 500 290L410 240L620 200L530 160C700 100 780 360 1100 160"
                            />
                            <path
                                id={`${effectId}-accent`}
                                d="M-100 200C180 40 480 460 480 310L600 260L560 330L740 200C880 100 940 300 1100 240"
                            />
                        </defs>
                        <use
                            href={`#${effectId}-secondary`}
                            className="SpinnerOverlay__haze"
                            filter={`url(#${effectId})`}
                        />
                        <use href={`#${effectId}-secondary`} className="SpinnerOverlay__trace" />
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
