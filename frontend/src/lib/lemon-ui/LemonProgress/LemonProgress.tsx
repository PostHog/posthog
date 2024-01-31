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
    const width = isNaN(percent) ? 0 : Math.max(Math.min(percent, 100), 0)

    return (
        <div
            className={clsx(
                'LemonProgress rounded-full w-full inline-block bg-bg-3000',
                size === 'large' ? 'h-5' : 'h-1.5',
                className
            )}
        >
            <span
                className={clsx(
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
}
