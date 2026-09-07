import clsx from 'clsx'
import { type ReactNode } from 'react'

import { LemonBanner, Spinner, Tooltip } from '@posthog/lemon-ui'

interface LiveChartCardProps {
    title: string
    subtitle?: string
    subtitleTooltip?: string
    isLoading: boolean
    errorMessage?: string
    children: ReactNode
    className?: string
    contentClassName?: string
}

export const LiveChartCard = ({
    title,
    subtitle,
    subtitleTooltip,
    isLoading,
    errorMessage,
    children,
    className = '',
    contentClassName = '',
}: LiveChartCardProps): JSX.Element => {
    return (
        <div className={clsx('bg-bg-light rounded-lg border p-4 h-full min-h-[340px] flex flex-col', className)}>
            <div className="flex items-baseline justify-between mb-4">
                <h3 className="text-sm font-semibold">{title}</h3>
                {subtitle &&
                    (subtitleTooltip ? (
                        <Tooltip title={subtitleTooltip}>
                            <span className="text-xs text-muted cursor-help">{subtitle}</span>
                        </Tooltip>
                    ) : (
                        <span className="text-xs text-muted">{subtitle}</span>
                    ))}
            </div>
            {isLoading ? (
                <div className="flex-1 flex items-center justify-center">
                    <Spinner className="text-2xl" />
                </div>
            ) : errorMessage ? (
                <div className="flex-1 flex items-center justify-center">
                    <LemonBanner type="error">{errorMessage}</LemonBanner>
                </div>
            ) : (
                <div className={clsx('flex-1 min-h-0', contentClassName)}>{children}</div>
            )}
        </div>
    )
}
