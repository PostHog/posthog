import clsx from 'clsx'
import './Spinner.scss'

export interface SpinnerProps {
    monocolor?: boolean
    className?: string
}

/** Smoothly animated spinner for loading states. It does not indicate progress, only that something's happening. */
export function Spinner({ monocolor = false, className }: SpinnerProps): JSX.Element {
    return (
        <svg
            className={clsx('Spinner', monocolor && `Spinner--monocolor`, className)}
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

export function SpinnerOverlay(
    props: SpinnerProps & {
        sceneLevel?: boolean
    }
): JSX.Element {
    return (
        <div className={clsx('SpinnerOverlay', props.sceneLevel && 'SpinnerOverlay--scene-level')}>
            <Spinner className="text-5xl" {...props} />
        </div>
    )
}
