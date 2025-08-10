import clsx from 'clsx'
import { forwardRef } from 'react'

export type LemonProgressProps = {
    size?: 'medium' | 'large'
    bgColor?: string
    strokeColor?: string
    percent: number
    /**
     * Whether to use a CSS transition for the bar. This is the default behavior.
     * Useful to disable if you already have smooth movement thanks to extremely frequent updates (50+ per second).
     * @default true
     */
    smoothing?: boolean
    children?: React.ReactNode
    className?: string
}

export const LemonProgress: React.FunctionComponent<LemonProgressProps & React.RefAttributes<HTMLDivElement>> =
    forwardRef(function LemonProgress(
        {
            size = 'medium',
            percent,
            smoothing = true,
            bgColor = 'var(--color-bg-primary)',
            strokeColor = 'var(--brand-blue)',
            children,
            className,
        },
        ref
    ): JSX.Element {
        const width = isNaN(percent) ? 0 : Math.max(Math.min(percent, 100), 0)

        return (
            <div
                ref={ref}
                className={clsx(
                    'LemonProgress rounded-full w-full inline-block',
                    size === 'large' ? 'h-5' : 'h-1.5',
                    className
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundColor: bgColor }}
            >
                <span
                    className={clsx(
                        'LemonProgress__track block h-full rounded-full',
                        width > 0 ? (size === 'large' ? 'min-w-5' : 'min-w-1.5') : null,
                        smoothing && 'transition-all'
                    )}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: `${width}%`, backgroundColor: strokeColor }}
                >
                    {children}
                </span>
            </div>
        )
    })
