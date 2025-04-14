import './Spinner.scss'

import { IconPencil } from '@posthog/icons'
import { twJoin, twMerge } from 'tailwind-merge'

export interface SpinnerProps {
    textColored?: boolean
    className?: string
    speed?: `${number}s` // Seconds
}

/** Smoothly animated spinner for loading states. It does not indicate progress, only that something's happening. */
export function Spinner({ textColored = false, className, speed = '1s' }: SpinnerProps): JSX.Element {
    return (
        <svg
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--spinner-speed': speed } as React.CSSProperties}
            className={twMerge('LemonIcon Spinner', textColored && `Spinner--textColored`, className)}
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
    return (
        <div className={twJoin('SpinnerOverlay', sceneLevel && 'SpinnerOverlay--scene-level')} aria-hidden={!visible}>
            {mode === 'editing' ? (
                <IconPencil className="text-5xl text-accent z-10 drop-shadow-xl" />
            ) : (
                <Spinner className={twMerge('text-5xl', className)} {...spinnerProps} />
            )}
        </div>
    )
}
