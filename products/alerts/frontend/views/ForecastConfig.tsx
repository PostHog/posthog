import { ForecastDetectorConfig, ForecastSideRule } from '~/queries/schema/schema-general'

import { ForecastSide, getForecastSideRules } from '../logic/forecastRules'
import { ForecastSideRuleFields } from './ForecastSideRuleFields'

export function ForecastConfig({
    config,
    onChange,
}: {
    config: ForecastDetectorConfig
    onChange: (config: ForecastDetectorConfig) => void
}): JSX.Element {
    const rules = getForecastSideRules(config)
    // The API reads a config with neither side as both default sides, so one side always stays on.
    const onlyOneSide = !rules.above || !rules.below

    const setSide = (side: ForecastSide, rule: ForecastSideRule | undefined): void => {
        const next: ForecastDetectorConfig = { type: 'forecast', ...rules, [side]: rule }
        if (!rule) {
            delete next[side]
        }
        onChange(next)
    }

    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <ForecastSideRuleFields
                side="above"
                rule={rules.above}
                onChange={(rule) => setSide('above', rule)}
                turnOffDisabledReason={onlyOneSide ? 'Watch at least one side.' : undefined}
            />
            <ForecastSideRuleFields
                side="below"
                rule={rules.below}
                onChange={(rule) => setSide('below', rule)}
                turnOffDisabledReason={onlyOneSide ? 'Watch at least one side.' : undefined}
            />
            <p className="text-xs text-muted">
                Each check forecasts the latest value from the values before it, then compares the actual value with the
                forecast. A side fires when every condition it sets is met. The forecast needs at least 30 earlier
                values.
            </p>
        </div>
    )
}
