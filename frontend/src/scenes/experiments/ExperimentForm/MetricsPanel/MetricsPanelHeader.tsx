import clsx from 'clsx'

import { IconCheckCircle, IconWarning } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

export const MetricsPanelHeader = ({
    experiment,
    sharedMetrics,
}: {
    experiment: Experiment
    sharedMetrics: { primary: ExperimentMetric[]; secondary: ExperimentMetric[] }
}): JSX.Element => {
    const primaryMetrics = [...(experiment.metrics || []), ...sharedMetrics.primary]
    const secondaryMetrics = [...(experiment.metrics_secondary || []), ...sharedMetrics.secondary]

    const primaryCount = primaryMetrics.length
    const secondaryCount = secondaryMetrics.length

    // Validation: experiments should have at least 1 primary metric
    const hasPrimaryMetrics = primaryCount > 0
    const isValid = hasPrimaryMetrics

    // Build summary
    const summaryParts: string[] = []

    if (primaryCount > 0) {
        summaryParts.push(`${primaryCount} primary metric${primaryCount > 1 ? 's' : ''}`)
    } else {
        summaryParts.push('No primary metrics configured')
    }

    if (secondaryCount > 0) {
        summaryParts.push(`${secondaryCount} secondary metric${secondaryCount > 1 ? 's' : ''}`)
    }

    const summaryText = summaryParts.join(' • ')

    return (
        <Tooltip title={`Metrics • ${summaryText}`}>
            <div className="flex items-center gap-2 w-full min-w-0">
                {isValid ? (
                    <IconCheckCircle className="text-success w-4 h-4 shrink-0" />
                ) : (
                    <IconWarning className="text-warning w-4 h-4 shrink-0" />
                )}
                <span className="font-semibold shrink-0">Metrics</span>
                <span className="text-muted shrink-0">•</span>
                <span className={clsx('text-sm truncate', isValid ? 'text-muted' : 'text-warning')}>{summaryText}</span>
            </div>
        </Tooltip>
    )
}
