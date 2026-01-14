import { ExperimentStatsMethod } from '~/types'

import { SelectableCard } from './SelectableCard'

export interface StatsMethodSelectorProps {
    value: ExperimentStatsMethod
    onChange: (method: ExperimentStatsMethod) => void
    disabled?: boolean
    disabledReason?: string
}

export function StatsMethodSelector({
    value,
    onChange,
    disabled,
    disabledReason,
}: StatsMethodSelectorProps): JSX.Element {
    return (
        <div className="flex gap-4 max-w-[800px]">
            <SelectableCard
                title="Bayesian"
                description="Gives you a clear win probability, showing how likely one variant is to be better than another. Great for product engineers new to experimentation."
                selected={value === ExperimentStatsMethod.Bayesian}
                onClick={() => !disabled && onChange(ExperimentStatsMethod.Bayesian)}
                disabled={disabled}
                disabledReason={disabledReason}
            />
            <SelectableCard
                title="Frequentist"
                description="Uses p-values to determine statistical significance. Often preferred by data scientists and teams experienced with traditional A/B testing."
                selected={value === ExperimentStatsMethod.Frequentist}
                onClick={() => !disabled && onChange(ExperimentStatsMethod.Frequentist)}
                disabled={disabled}
                disabledReason={disabledReason}
            />
        </div>
    )
}
