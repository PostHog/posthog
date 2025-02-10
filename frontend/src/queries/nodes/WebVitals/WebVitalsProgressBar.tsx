import clsx from 'clsx'

import { WebVitalsMetric, WebVitalsMetricBand } from '~/queries/schema'

import { computePositionInBand, getMetricBand, getThresholdColor, WEB_VITALS_THRESHOLDS } from './definitions'

interface WebVitalsProgressBarProps {
    value?: number
    metric: WebVitalsMetric
}

export function WebVitalsProgressBar({ value, metric }: WebVitalsProgressBarProps): JSX.Element {
    const band = getMetricBand(value, metric)

    const threshold = WEB_VITALS_THRESHOLDS[metric]
    const goodWidth = (threshold.good / threshold.end) * 100
    const improvementsWidth = ((threshold.poor - threshold.good) / threshold.end) * 100
    const poorWidth = 100 - goodWidth - improvementsWidth

    return (
        <div className="w-full h-1 rounded-full relative">
            {/* Green segment up to "good" threshold */}
            <div
                className={clsx('absolute h-full rounded-full', band === 'good' ? 'bg-success' : 'bg-surface-tooltip')}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: `${goodWidth}%` }}
            >
                <IndicatorLine value={value} metric={metric} band="good" />
            </div>

            {/* Yellow segment up to "poor" threshold */}
            <div
                className={clsx(
                    'absolute h-full rounded-full',
                    band === 'needs_improvements' ? 'bg-warning' : 'bg-surface-tooltip'
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: `${goodWidth + 1}%`, width: `${improvementsWidth - 1}%` }}
            >
                <IndicatorLine value={value} metric={metric} band="needs_improvements" />
            </div>

            {/* Red segment after "poor" threshold */}
            <div
                className={clsx('absolute h-full rounded-full', band === 'poor' ? 'bg-danger' : 'bg-surface-tooltip')}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: `${goodWidth + improvementsWidth + 1}%`, width: `${poorWidth - 1}%` }}
            >
                <IndicatorLine value={value} metric={metric} band="poor" />
            </div>
        </div>
    )
}

type IndicatorLineProps = {
    value: number | undefined
    metric: WebVitalsMetric
    band: WebVitalsMetricBand | 'none'
}

const IndicatorLine = ({ value, metric, band }: IndicatorLineProps): JSX.Element | null => {
    if (!value) {
        return null
    }

    const thisBand = getMetricBand(value, metric)
    if (thisBand !== band) {
        return null
    }

    const positionInBand = computePositionInBand(value, metric)
    const color = getThresholdColor(value, metric)

    return (
        <div
            // eslint-disable-next-line react/forbid-dom-props
            style={{ left: `${positionInBand * 100}%` }}
            className={clsx('absolute w-0.5 h-3 -top-1', `bg-${color}`)}
        />
    )
}
