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
    const isDisabled = disabled ?? false
    const reason = disabledReason ?? ''
    const disabledProps = isDisabled ? { disabled: true, disabledReason: reason || 'Disabled' } : {}

    return (
        <div className="flex gap-4 max-w-[800px]">
            <SelectableCard
                title="Bayesian"
                description="Gives you a clear win probability, showing how likely one variant is to be better than another. Great for product engineers new to experimentation."
                selected={value === ExperimentStatsMethod.Bayesian}
                onClick={() => !isDisabled && onChange(ExperimentStatsMethod.Bayesian)}
                {...disabledProps}
            />
            <SelectableCard
                title="Frequentist"
                description="Uses p-values to determine statistical significance. Often preferred by data scientists and teams experienced with traditional A/B testing."
                selected={value === ExperimentStatsMethod.Frequentist}
                onClick={() => !isDisabled && onChange(ExperimentStatsMethod.Frequentist)}
                {...disabledProps}
            />
        </div>
    )
}
