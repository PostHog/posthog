import type { OfflineScorerVersionReadApi, NumericScoreDefinitionConfigApi } from '../generated/api.schemas'
import {
    getBooleanConfig,
    getCategoricalConfig,
    getNumericConfig,
} from '../scoreDefinitions/scoreDefinitionConfigUtils'

type OfflineScorerConfig = Pick<OfflineScorerVersionReadApi, 'kind' | 'config'>

export function offlineBooleanPolarity(scorer: OfflineScorerConfig): boolean | null {
    return scorer.kind === 'boolean' ? getBooleanConfig(scorer.config).true_is_failure === true : null
}

export function offlineNumericPassingRule(
    scorer: OfflineScorerConfig
): NumericScoreDefinitionConfigApi['passing_rule'] | null {
    const rule = scorer.kind === 'numeric' ? getNumericConfig(scorer.config).passing_rule : null
    return rule && Number.isFinite(rule.threshold) && (rule.operator === 'gte' || rule.operator === 'lte') ? rule : null
}

export function offlineScoreHasPassingRule(scorer: OfflineScorerConfig): boolean {
    return (
        offlineBooleanPolarity(scorer) !== null ||
        offlineNumericPassingRule(scorer) !== null ||
        offlineCategoricalPassingRule(scorer) !== null
    )
}

export function offlineCategoricalPassingRule(scorer: OfflineScorerConfig): string[] | null {
    return scorer.kind === 'categorical' ? (getCategoricalConfig(scorer.config).passing_rule?.categories ?? null) : null
}

export function offlineScorePasses(value: unknown, scorer: OfflineScorerConfig): boolean | null {
    if (scorer.kind === 'boolean' && typeof value === 'boolean') {
        const polarity = offlineBooleanPolarity(scorer)
        return polarity === null ? null : value !== polarity
    }
    if (scorer.kind === 'numeric' && typeof value === 'number' && Number.isFinite(value)) {
        const rule = offlineNumericPassingRule(scorer)
        return rule ? (rule.operator === 'gte' ? value >= rule.threshold : value <= rule.threshold) : null
    }
    if (scorer.kind === 'categorical' && Array.isArray(value)) {
        const categories = offlineCategoricalPassingRule(scorer)
        return categories === null
            ? null
            : value.length === 0
              ? categories.length === 0
              : value.every((key) => categories.includes(key))
    }
    return null
}
