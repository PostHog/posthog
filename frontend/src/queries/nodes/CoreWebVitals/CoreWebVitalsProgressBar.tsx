import clsx from 'clsx'
import { CoreWebVitalsThreshold } from 'scenes/web-analytics/webAnalyticsLogic'

import { getMetricBand, getThresholdColor } from './definitions'

interface CoreWebVitalsProgressBarProps {
    value?: number
    threshold: CoreWebVitalsThreshold
}

export function CoreWebVitalsProgressBar({ value, threshold }: CoreWebVitalsProgressBarProps): JSX.Element {
    const indicatorPercentage = Math.min((value ?? 0 / threshold.end) * 100, 100)

    const thresholdColor = getThresholdColor(value, threshold)
    const band = getMetricBand(value, threshold)

    const goodWidth = (threshold.good / threshold.end) * 100
    const improvementsWidth = ((threshold.poor - threshold.good) / threshold.end) * 100
    const poorWidth = 100 - goodWidth - improvementsWidth

    return (
        <div className="w-full h-1 rounded-full relative">
            {/* Green segment up to "good" threshold */}
            <div
                className={clsx('absolute h-full rounded-full', band === 'good' ? 'bg-success' : 'bg-muted')}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: `${goodWidth}%` }}
            />

            {/* Yellow segment up to "poor" threshold */}
            <div
                className={clsx('absolute h-full rounded-full', band === 'improvements' ? 'bg-warning' : 'bg-muted')}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: `${goodWidth + 1}%`, width: `${improvementsWidth - 1}%` }}
            />

            {/* Red segment after "poor" threshold */}
            <div
                className={clsx('absolute h-full rounded-full', band === 'poor' ? 'bg-danger' : 'bg-muted')}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: `${goodWidth + improvementsWidth + 1}%`, width: `${poorWidth - 1}%` }}
            />

            {/* Indicator line */}
            {value != null && (
                <div
                    className={clsx('absolute w-0.5 h-3 -top-1', `bg-${thresholdColor}`)}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        left: `${indicatorPercentage}%`,
                        transform: 'translateX(-50%)',
                    }}
                />
            )}
        </div>
    )
}
