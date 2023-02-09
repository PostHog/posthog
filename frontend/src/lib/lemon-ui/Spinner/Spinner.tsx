import clsx from 'clsx'
import { IconSpinner } from 'lib/lemon-ui/icons'
import './Spinner.scss'

export interface SpinnerProps {
    monocolor?: boolean
    className?: string
}

/** Smoothly animated spinner for loading states. It does not indicate progress, only that something's happening. */
export function Spinner({ monocolor, className }: SpinnerProps): JSX.Element {
    return <IconSpinner monocolor={monocolor} className={clsx('Spinner', className)} />
}

export function SpinnerOverlay(props: SpinnerProps): JSX.Element {
    return (
        <div className="SpinnerOverlay">
            <Spinner className="text-4xl" {...props} />
        </div>
    )
}
