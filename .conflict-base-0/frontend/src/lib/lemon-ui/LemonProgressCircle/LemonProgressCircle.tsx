import './LemonProgressCircle.scss'

import clsx from 'clsx'

export type LemonProgressCircleProps = {
    strokePercentage?: number
    backgroundStrokeOpacity?: number
    size?: number
    progress: number
    children?: React.ReactNode
    className?: string
}

export const LemonProgressCircle = ({
    strokePercentage = 0.2,
    backgroundStrokeOpacity = 0.2,
    size = 16,
    progress,
    children,
    className,
}: LemonProgressCircleProps): JSX.Element => {
    const radius = size / 2
    const stroke = radius * strokePercentage
    const circumference = size * Math.PI
    const strokeDashoffset = circumference - progress * circumference

    return (
        <span
            className={clsx('LemonProgressCircle', className)}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                height: size,
                width: size,
            }}
        >
            <svg height={size} width={size}>
                <circle
                    stroke="currentColor"
                    strokeOpacity={backgroundStrokeOpacity}
                    fill="transparent"
                    strokeWidth={stroke}
                    r={radius - stroke / 2}
                    cx={radius}
                    cy={radius}
                />

                <circle
                    stroke="currentColor"
                    fill="transparent"
                    strokeWidth={stroke}
                    strokeDasharray={circumference + ' ' + circumference}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ strokeDashoffset }}
                    r={radius - stroke / 2}
                    cx={radius}
                    cy={radius}
                />
            </svg>

            {children ? <span className="LemonProgressCircle__content">{children}</span> : null}
        </span>
    )
}
