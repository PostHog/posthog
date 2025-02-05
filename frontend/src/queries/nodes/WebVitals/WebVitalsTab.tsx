import './WebVitalsTab.scss'

import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'

import { WebVitalsMetric } from '~/queries/schema'

import { getThresholdColor, getValueWithUnit, LONG_METRIC_NAME, METRIC_DESCRIPTION } from './definitions'
import { WebVitalsProgressBar } from './WebVitalsProgressBar'

type WebVitalsTabProps = {
    value: number | undefined
    metric: WebVitalsMetric
    isActive: boolean
    setTab?: () => void
}

export function WebVitalsTab({ value, metric, isActive, setTab }: WebVitalsTabProps): JSX.Element {
    const label = LONG_METRIC_NAME[metric]

    const { value: parsedValue, unit } = getValueWithUnit(value, metric)
    const thresholdColor = getThresholdColor(value, metric)

    return (
        <div
            onClick={setTab}
            className="WebVitals__WebVitalsTab flex flex-1 flex-row sm:flex-col justify-around sm:justify-start items-center sm:items-start p-4"
            data-active={isActive ? 'true' : 'false'}
        >
            <div className="text-sm hidden sm:flex w-full flex-row justify-between">
                <span>{label}</span>
                <Tooltip title={METRIC_DESCRIPTION[metric]}>
                    <IconInfo />
                </Tooltip>
            </div>
            <span className="text-sm block sm:hidden">
                <Tooltip title={label}>{metric}</Tooltip>
            </span>

            <div className="flex flex-row items-end">
                <span className={clsx('text-2xl', `text-${thresholdColor}`)}>
                    {parsedValue || <LemonSkeleton fade className="w-20 h-8" />}
                </span>
                <span className="text-xs ml-1 mb-1">{unit}</span>
            </div>

            <div className="w-full mt-2 hidden sm:block">
                <WebVitalsProgressBar value={value} metric={metric} />
            </div>
        </div>
    )
}
