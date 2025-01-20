import './WebVitalsTab.scss'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { WEB_VITALS_THRESHOLDS } from 'scenes/web-analytics/webAnalyticsLogic'

import { WebVitalsMetric } from '~/queries/schema'

import { getThresholdColor, getValueWithUnit } from './definitions'
import { WebVitalsProgressBar } from './WebVitalsProgressBar'

type WebVitalsTabProps = {
    value: number | undefined
    label: string
    metric: WebVitalsMetric
    isActive: boolean
    setTab?: () => void
    inSeconds?: boolean
}

export function WebVitalsTab({
    value,
    label,
    metric,
    isActive,
    setTab,
    inSeconds = false,
}: WebVitalsTabProps): JSX.Element {
    const { value: parsedValue, unit } = getValueWithUnit(value, inSeconds)

    const threshold = WEB_VITALS_THRESHOLDS[metric]
    const thresholdColor = getThresholdColor(value, threshold)

    return (
        <div
            onClick={setTab}
            className="WebVitals__WebVitalsTab flex flex-1 flex-row sm:flex-col justify-around sm:justify-start items-center sm:items-start p-4"
            data-active={isActive ? 'true' : 'false'}
        >
            <span className="text-sm hidden sm:block">{label}</span>
            <span className="text-sm block sm:hidden">
                <Tooltip title={label}>{metric}</Tooltip>
            </span>

            <div className="flex flex-row items-end">
                <span className={clsx('text-2xl', `text-${thresholdColor}`)}>
                    {parsedValue || <LemonSkeleton fade className="w-20 h-8" />}
                </span>
                {inSeconds && <span className="text-xs ml-1 mb-1">{unit}</span>}
            </div>

            <div className="w-full mt-2 hidden sm:block">
                <WebVitalsProgressBar value={value} threshold={threshold} />
            </div>
        </div>
    )
}
