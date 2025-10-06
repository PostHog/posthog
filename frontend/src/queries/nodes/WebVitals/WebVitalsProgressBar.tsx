import { WebVitalsMetric, WebVitalsMetricBand } from '~/queries/schema/schema-general'

import {
    WEB_VITALS_COLORS,
    WEB_VITALS_THRESHOLDS,
    computePositionInBand,
    getMetricBand,
    getThresholdColor,
} from './definitions'

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
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    width: `${goodWidth}%`,
                    backgroundColor: band === 'good' ? `${WEB_VITALS_COLORS.good} !important` : undefined,
                }}
                className="absolute h-full rounded-full bg-surface-secondary"
            >
                <IndicatorLine value={value} metric={metric} band="good" />
            </div>

            {/* Yellow segment up to "poor" threshold */}
            <div
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    left: `${goodWidth + 1}%`,
                    width: `${improvementsWidth - 1}%`,
                    backgroundColor:
                        band === 'needs_improvements'
                            ? `${WEB_VITALS_COLORS.needs_improvements} !important`
                            : undefined,
                }}
                className="absolute h-full rounded-full bg-surface-secondary"
            >
                <IndicatorLine value={value} metric={metric} band="needs_improvements" />
            </div>

            {/* Red segment after "poor" threshold */}
            <div
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    left: `${goodWidth + improvementsWidth + 1}%`,
                    width: `${poorWidth - 1}%`,
                    backgroundColor: band === 'poor' ? `${WEB_VITALS_COLORS.poor} !important` : undefined,
                }}
                className="absolute h-full rounded-full bg-surface-secondary"
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
    const backgroundColor = getThresholdColor(value, metric)

    return (
        <div
            // eslint-disable-next-line react/forbid-dom-props
            style={{ left: `${positionInBand * 100}%`, backgroundColor }}
            className="absolute w-0.5 h-3 -top-1"
        />
    )
}
