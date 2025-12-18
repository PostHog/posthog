import { IconCheckCircle, IconWarning } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { Experiment } from '~/types'

export const ExperimentDetailsPanelHeader = ({ experiment }: { experiment: Experiment }): JSX.Element => {
    const hasName = experiment.name && experiment.name.trim().length > 0
    const isValid = hasName

    const summaryText = hasName ? experiment.name : 'Untitled'

    return (
        <Tooltip title={`Experiment details • ${summaryText}`}>
            <div className="flex items-center gap-2 w-full min-w-0">
                {isValid ? (
                    <IconCheckCircle className="text-success w-4 h-4 shrink-0" />
                ) : (
                    <IconWarning className="text-warning w-4 h-4 shrink-0" />
                )}
                <span className="font-semibold shrink-0">Experiment details</span>
                <span className="text-muted shrink-0">•</span>
                <span className="text-sm text-muted truncate">{summaryText}</span>
            </div>
        </Tooltip>
    )
}
