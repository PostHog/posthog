import { IconCheckCircle } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { ExperimentEventExposureConfig } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

export const ExposureCriteriaPanelHeader = ({ experiment }: { experiment: Experiment }): JSX.Element => {
    const isCustom = !!experiment.exposure_criteria?.exposure_config
    const customEvent = isCustom
        ? (experiment.exposure_criteria?.exposure_config as ExperimentEventExposureConfig).event
        : null
    const hasTestAccountFilter = experiment.exposure_criteria?.filterTestAccounts

    const summaryParts: string[] = []
    summaryParts.push(isCustom && customEvent ? `Custom: ${customEvent}` : 'Default trigger')
    if (hasTestAccountFilter) {
        summaryParts.push('Filter test accounts')
    }

    const summaryText = summaryParts.join(' • ')

    return (
        <Tooltip title={`Exposure criteria • ${summaryText}`}>
            <div className="flex items-center gap-2 w-full min-w-0">
                <IconCheckCircle className="text-success w-4 h-4 shrink-0" />
                <span className="font-semibold shrink-0">Exposure criteria</span>
                <span className="text-muted shrink-0">•</span>
                <span className="text-sm text-muted truncate">{summaryText}</span>
            </div>
        </Tooltip>
    )
}
