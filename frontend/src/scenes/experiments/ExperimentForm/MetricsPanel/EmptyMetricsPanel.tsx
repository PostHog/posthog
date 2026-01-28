import clsx from 'clsx'

import { IconAreaChart } from 'lib/lemon-ui/icons'
import { AddMetricButton } from 'scenes/experiments/Metrics/AddMetricButton'

import { MetricContext } from '~/scenes/experiments/Metrics/experimentMetricModalLogic'

export type EmptyMetricsPanelProps = {
    metricContext: MetricContext
    className?: string
}

export const EmptyMetricsPanel = ({ metricContext, className }: EmptyMetricsPanelProps): JSX.Element => (
    <div className={clsx('border rounded bg-surface-primary pt-6 pb-8 text-secondary', className)}>
        <div className="flex flex-col items-center mx-auto deprecated-space-y-3">
            <IconAreaChart fontSize="30" />
            <div className="text-sm text-center text-balance max-w-sm">
                <p>
                    {metricContext.type === 'secondary'
                        ? 'Secondary metrics provide additional context and help detect unintended side effects.'
                        : 'Primary metrics represent the main goal of the experiment and directly measure if your hypothesis was successful.'}
                </p>
            </div>
            <AddMetricButton metricContext={metricContext} />
        </div>
    </div>
)
