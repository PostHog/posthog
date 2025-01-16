import './CoreWebVitalsTab.scss'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { CORE_WEB_VITALS_THRESHOLDS } from 'scenes/web-analytics/webAnalyticsLogic'

import { CoreWebVitalsMetric } from '~/queries/schema'

import { CoreWebVitalsProgressBar } from './CoreWebVitalsProgressBar'
import { getThresholdColor, getValueWithUnit } from './definitions'

type CoreWebVitalsTabProps = {
    value: number | undefined
    label: string
    metric: CoreWebVitalsMetric
    isActive: boolean
    setTab?: () => void
    inSeconds?: boolean
}

export function CoreWebVitalsTab({
    value,
    label,
    metric,
    isActive,
    setTab,
    inSeconds = false,
}: CoreWebVitalsTabProps): JSX.Element {
    // TODO: Go back to using an actual value
    // Will keep this as is while we test what the UI looks like
    // const {value: parsedValue, unit } = getValueWithUnit(value, inSeconds)
    const newValue = true ? (inSeconds ? Math.random() * 10000 : Math.random()) : value
    const { value: parsedValue, unit } = getValueWithUnit(newValue, inSeconds)

    const threshold = CORE_WEB_VITALS_THRESHOLDS[metric]
    const thresholdColor = getThresholdColor(newValue, threshold)

    return (
        <div
            onClick={setTab}
            className="CoreWebVitals__CoreWebVitalsTab flex flex-1 flex-row sm:flex-col justify-around sm:justify-start items-center sm:items-start p-4"
            data-active={isActive ? 'true' : 'false'}
        >
            <span className="text-sm hidden sm:block">{label}</span>
            <span className="text-sm block sm:hidden">
                <Tooltip title={label}>{metric}</Tooltip>
            </span>

            <div className="flex flex-row items-end">
                <span className={clsx('text-2xl', `text-${thresholdColor}`)}>
                    {parsedValue || <LemonSkeleton fade className="w-4 h-4" />}
                </span>
                {inSeconds && <span className="text-xs ml-1 mb-1">{unit}</span>}
            </div>

            <div className="w-full mt-2 hidden sm:block">
                {newValue && <CoreWebVitalsProgressBar value={newValue} threshold={threshold} />}
            </div>
        </div>
    )
}
