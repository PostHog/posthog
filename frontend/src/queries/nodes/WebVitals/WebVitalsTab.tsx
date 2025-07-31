import clsx from 'clsx'

import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { WebVitalsMetric } from '~/queries/schema/schema-general'

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
                'flex-1 gap-2 border p-2 bg-surface-primary rounded items-center sm:items-start flex flex-col justify-between cursor-pointer',
                isActive && 'border-accent border-2'
            )}
        >
            <div className="text-sm hidden sm:flex w-full flex-row justify-between">
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
