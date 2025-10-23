import { IconCheckCircle, IconWarning } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { Experiment } from '~/types'

export const MetricsPanelHeader = ({ experiment }: { experiment: Experiment }): JSX.Element => {
    const primaryMetrics = experiment.metrics || []
    const secondaryMetrics = experiment.metrics_secondary || []

    const primaryCount = primaryMetrics.length
    const secondaryCount = secondaryMetrics.length

    // Validation: experiments should have at least 1 primary metric
    const hasPrimaryMetrics = primaryCount > 0
    const isValid = hasPrimaryMetrics

    // Build summary
    const summaryParts: string[] = []

    if (primaryCount === 0) {
        summaryParts.push('No metrics configured')
    } else if (primaryCount === 1) {
        summaryParts.push('1 primary metric')
    } else {
        summaryParts.push(`${primaryCount} primary metrics`)
    }

    if (secondaryCount > 0) {
        summaryParts.push(`${secondaryCount} secondary`)
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
                <span className="text-sm text-muted truncate">{summaryText}</span>
            </div>
        </Tooltip>
    )
}
