import { getBooleanConfig, getCategoricalConfig, getNumericConfig } from './scoreDefinitionConfigUtils'
import { getScoreDefinitionOptionKey, type ScoreDefinitionDraft } from './scoreDefinitionModalUtils'

function passingExpression(input: ScoreDefinitionDraft['inputs'][number]): string | null {
    if (!input.config) {
        return null
    }
    if (input.kind === 'boolean') {
        return getBooleanConfig(input.config).true_is_failure ? `not ${input.alias}` : input.alias
    }
    if (input.kind === 'numeric') {
        const rule = getNumericConfig(input.config).passing_rule
        return rule ? `${input.alias} ${rule.operator === 'gte' ? '>=' : '<='} ${rule.threshold}` : null
    }
    const config = getCategoricalConfig(input.config)
    const passing = config.passing_rule?.categories
    if (!passing?.length) {
        return null
    }
    const positive = passing.map((key) => `${JSON.stringify(key)} in ${input.alias}`).join(' or ')
    const failing = config.options.filter((option) => !passing.includes(option.key))
    return failing.length
        ? `(${positive}) and not (${failing.map((option) => `${JSON.stringify(option.key)} in ${input.alias}`).join(' or ')})`
        : positive
}

export function defaultCompositeExpression(draft: ScoreDefinitionDraft): string | null {
    if (!draft.inputs.length) {
        return ''
    }
    if (draft.kind === 'numeric') {
        const terms = draft.inputs.map((input) => {
            if (input.kind === 'numeric') {
                return input.alias
            }
            const passing = passingExpression(input)
            return passing ? `number(${passing})` : null
        })
        return terms.some((term) => term === null)
            ? null
            : terms.length === 1
              ? terms[0]
              : `(${terms.join(' + ')}) / ${terms.length}`
    }
    const conditions = draft.inputs.map(passingExpression)
    if (conditions.some((condition) => condition === null)) {
        return null
    }
    const condition = conditions.map((part) => `(${part})`).join(' and ')
    if (draft.kind === 'boolean') {
        return draft.booleanPassing === 'false' ? `not (${condition})` : condition
    }
    const keys = draft.options.map(getScoreDefinitionOptionKey).filter(Boolean)
    const passing = draft.categoricalPassingEnabled ? draft.categoricalPassingCategories : keys.slice(0, 1)
    const pass = keys.find((key) => passing.includes(key))
    const fail = keys.find((key) => !passing.includes(key))
    return pass && fail ? `${JSON.stringify(pass)} if ${condition} else ${JSON.stringify(fail)}` : null
}

export function updateScorerDraft(
    draft: ScoreDefinitionDraft,
    field: keyof ScoreDefinitionDraft,
    value: ScoreDefinitionDraft[keyof ScoreDefinitionDraft]
): ScoreDefinitionDraft {
    const next = { ...draft, [field]: value }
    if (field === 'expression') {
        next.expressionIsCustom = true
    }
    if (next.calculation === 'composite' && !next.expressionIsCustom) {
        next.expression = defaultCompositeExpression(next) ?? ''
    }
    return next
}
