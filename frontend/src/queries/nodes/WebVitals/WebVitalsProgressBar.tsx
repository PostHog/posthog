import clsx from 'clsx'
import { WebVitalsThreshold } from 'scenes/web-analytics/webAnalyticsLogic'

import { WebVitalsMetricBand } from '~/queries/schema'

import { computePositionInBand, getMetricBand, getThresholdColor } from './definitions'

interface WebVitalsProgressBarProps {
    value?: number
    threshold: WebVitalsThreshold
}

export function WebVitalsProgressBar({ value, threshold }: WebVitalsProgressBarProps): JSX.Element {
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
            >
                <IndicatorLine value={value} threshold={threshold} band="good" />
            </div>

            {/* Yellow segment up to "poor" threshold */}
            <div
                className={clsx(
                    'absolute h-full rounded-full',
                    band === 'needs_improvements' ? 'bg-warning' : 'bg-muted'
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: `${goodWidth + 1}%`, width: `${improvementsWidth - 1}%` }}
            >
                <IndicatorLine value={value} threshold={threshold} band="needs_improvements" />
            </div>

            {/* Red segment after "poor" threshold */}
            <div
                className={clsx('absolute h-full rounded-full', band === 'poor' ? 'bg-danger' : 'bg-muted')}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: `${goodWidth + improvementsWidth + 1}%`, width: `${poorWidth - 1}%` }}
            >
                <IndicatorLine value={value} threshold={threshold} band="poor" />
            </div>
        </div>
    )
}

type IndicatorLineProps = {
    value: number | undefined
    threshold: WebVitalsThreshold
    band: WebVitalsMetricBand | 'none'
}

const IndicatorLine = ({ value, threshold, band }: IndicatorLineProps): JSX.Element | null => {
    if (!value) {
        return null
    }

    const thisBand = getMetricBand(value, threshold)
    if (thisBand !== band) {
        return null
    }

    const positionInBand = computePositionInBand(value, threshold)
    const color = getThresholdColor(value, threshold)

    return (
        <div
            // eslint-disable-next-line react/forbid-dom-props
            style={{ left: `${positionInBand * 100}%` }}
            className={clsx('absolute w-0.5 h-3 -top-1', `bg-${color}`)}
        />
    )
}
