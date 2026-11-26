import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import type { FeatureFlagRulesV2ExperimentRule, FeatureFlagType } from '~/types'

import { isRulesV2FeatureFlagConfig } from 'products/feature_flags/frontend/featureFlagConfigFormat'

import { experimentRuleIneligibleReason, getFlagExperimentRule, getFlagExperimentRules } from './utils'

// Rules are numbered by their position in the flag, as on the flag's page
const ruleLabel = (flag: FeatureFlagType, rule: FeatureFlagRulesV2ExperimentRule): string => {
    const position = isRulesV2FeatureFlagConfig(flag.filters) ? flag.filters.rules.indexOf(rule) + 1 : 0
    return rule.description ? `Rule ${position}: ${rule.description}` : `Rule ${position}`
}

interface ExperimentRuleSelectProps {
    flag: FeatureFlagType
    ruleId: string | null | undefined
    onChange?: (ruleId: string) => void
    disabledReason?: string
}

export function ExperimentRuleSelect({
    flag,
    ruleId,
    onChange,
    disabledReason,
}: ExperimentRuleSelectProps): JSX.Element | null {
    const experimentRules = getFlagExperimentRules(flag)
    if (experimentRules.length === 0) {
        return null
    }
    return (
        <LemonField.Pure
            label="Experiment rule"
            info="The experiment counts the exposures of this rule of the flag."
            htmlFor="experiment-flag-rule"
        >
            <LemonSelect
                id="experiment-flag-rule"
                size="small"
                value={getFlagExperimentRule(flag, ruleId)?.id ?? null}
                onChange={(value) => value && onChange?.(value)}
                options={experimentRules.map((rule) => ({
                    value: rule.id,
                    label: ruleLabel(flag, rule),
                    disabledReason: experimentRuleIneligibleReason(rule) ?? undefined,
                }))}
                placeholder="Select an experiment rule"
                disabledReason={disabledReason ?? (onChange ? undefined : 'The rule cannot be changed here.')}
                data-attr="experiment-flag-rule"
            />
        </LemonField.Pure>
    )
}
