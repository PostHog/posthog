import { cn } from 'lib/utils/css-classes'
import { forwardRef } from 'react'

export type LemonProgressProps = {
    size?: 'medium' | 'large'
    bgColor?: string
    strokeColor?: string
    percent: number
    children?: React.ReactNode
    className?: string
}

export const LemonProgress: React.FunctionComponent<LemonProgressProps & React.RefAttributes<HTMLDivElement>> =
    forwardRef(function LemonProgress(
        {
            size = 'medium',
            percent,
            bgColor = 'var(--bg-primary)',
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
                className={cn(
                    'LemonProgress rounded-full w-full inline-block',
                    size === 'large' ? 'h-5' : 'h-1.5',
                    className
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundColor: bgColor }}
            >
                <span
                    className={cn(
                        'LemonProgress__track block h-full rounded-full transition-all',
                        width > 0 ? (size === 'large' ? 'min-w-5' : 'min-w-1.5') : null
                    )}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: `${width}%`, backgroundColor: strokeColor }}
                >
                    {children}
                </span>
            </div>
        )
    })
