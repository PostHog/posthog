import clsx from 'clsx'

import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { WebVitalsMetric } from '~/schema'

import { WebVitalsProgressBar } from './WebVitalsProgressBar'
import { LONG_METRIC_NAME, METRIC_DESCRIPTION, getThresholdColor, getValueWithUnit } from './definitions'

type WebVitalsTabProps = {
    value: number | undefined
    metric: WebVitalsMetric
    isActive: boolean
    setTab?: () => void
}

export function WebVitalsTab({ value, metric, isActive, setTab }: WebVitalsTabProps): JSX.Element {
    const label = LONG_METRIC_NAME[metric]

    const { value: parsedValue, unit } = getValueWithUnit(value, metric)
    const color = getThresholdColor(value, metric)

    return (
        <div
            onClick={setTab}
            className={clsx(
                'bg-surface-primary flex flex-1 cursor-pointer flex-col items-center justify-between gap-2 rounded border p-2 sm:items-start',
                isActive && 'border-accent border-2'
            )}
        >
            <div className="hidden w-full flex-row justify-between text-sm sm:flex">
                <span>
                    {label} ({metric})
                </span>
                <Tooltip title={METRIC_DESCRIPTION[metric]}>
                    <IconInfo />
                </Tooltip>
            </div>
            <div className="flex flex-col items-center sm:hidden">
                <span className="text-sm font-bold">{metric}</span>
                <span className="text-xs">{label}</span>
            </div>

            <div className="flex flex-row items-end">
                <span
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ color }}
                    className="text-2xl"
                >
                    {parsedValue || <LemonSkeleton fade className="h-8 w-20" />}
                </span>
                <span className="mb-1 ml-1 text-xs">{unit}</span>
            </div>

            <div className="mt-2 hidden w-full sm:block">
                <WebVitalsProgressBar value={value} metric={metric} />
            </div>
        </div>
    )
}
