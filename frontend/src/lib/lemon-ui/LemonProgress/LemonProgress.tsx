import './LemonProgress.scss'

import clsx from 'clsx'

export type LemonProgressProps = {
    size?: 'medium' | 'large'
    strokeColor?: string
    percent: number
    children?: React.ReactNode
    className?: string
}

export const LemonProgress = ({
    size = 'medium',
    percent,
    strokeColor = 'var(--brand-blue)',
    children,
    className,
}: LemonProgressProps): JSX.Element => {
    return (
        <div
            className={clsx(
                'LemonProgress rounded-full w-full inline-block bg-bg-3000',
                size === 'large' ? 'h-5' : 'h-[0.375rem]',
                className
            )}
        >
            <span
                className={clsx(
                    'LemonProgress__track block h-full rounded-full',
                    percent > 0 ? (size === 'large' ? 'min-w-5' : 'min-w-[0.375rem]') : null
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: `${percent}%`, backgroundColor: strokeColor }}
            >
                {children}
            </span>
        </div>
    )
}
