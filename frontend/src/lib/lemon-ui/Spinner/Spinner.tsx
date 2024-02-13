import './Spinner.scss'

import clsx from 'clsx'
import { IconSchedule } from 'lib/lemon-ui/icons'

export interface SpinnerProps {
    textColored?: boolean
    className?: string
}

/** Smoothly animated spinner for loading states. It does not indicate progress, only that something's happening. */
export function Spinner({ textColored = false, className }: SpinnerProps): JSX.Element {
    return (
        <svg
            className={clsx('LemonIcon Spinner', textColored && `Spinner--textColored`, className)}
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
    mode?: 'spinning' | 'waiting'
}): JSX.Element {
    return (
        <div className={clsx('SpinnerOverlay', sceneLevel && 'SpinnerOverlay--scene-level')} aria-hidden={!visible}>
            {mode === 'waiting' ? (
                <IconSchedule className="text-5xl text-primary z-10 animate-pulse drop-shadow-xl" />
            ) : (
                <Spinner className={clsx('text-5xl', className)} {...spinnerProps} />
            )}
        </div>
    )
}
