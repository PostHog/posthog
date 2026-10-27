import { IconCheck, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { MAX_CATEGORICAL_OPTIONS } from '../constants'
import type { EvaluationOutputConfig } from '../types'
import { categoryKey } from './categoryKey'

/**
 * The categories of a new evaluation. Keys follow the labels, because nothing has stored them yet, and marking a
 * category as a pass is the passing rule: with none picked, runs get no pass or fail.
 */
export function EvaluationCategoryEditor({
    config,
    onChange,
    showKeys,
}: {
    config: EvaluationOutputConfig
    onChange: (patch: EvaluationOutputConfig) => void
    /** Code returns the key, so a code evaluation shows it next to each name. */
    showKeys: boolean
}): JSX.Element {
    const options = config.options ?? []
    const passing = config.passing_rule && 'categories' in config.passing_rule ? config.passing_rule.categories : []
    const named = options.filter((option) => option.key)
    // With several categories an empty rule means "passes when none is found", so an existing rule stays when emptied.
    const keepsEmptyRule = config.selection_mode === 'multiple' && !!config.passing_rule
    const withPassing = (keys: string[]): EvaluationOutputConfig['passing_rule'] =>
        keys.length > 0 || keepsEmptyRule ? { categories: keys } : null

    return (
        <div className="flex flex-col gap-2">
            {options.map((option, index) => (
                <div key={index} className="flex items-center gap-2">
                    <Tooltip title={option.key ? `Stored as ${option.key}` : undefined} placement="top-start">
                        <LemonInput
                            className="flex-1 min-w-0"
                            aria-label={`Category ${index + 1}`}
                            placeholder={index === 0 ? 'For example, Resolved' : 'Category'}
                            value={option.label}
                            maxLength={256}
                            onChange={(label) => {
                                const key = categoryKey(label)
                                onChange({
                                    options: options.map((item, i) => (i === index ? { label, key } : item)),
                                    passing_rule: withPassing(
                                        passing.map((value) => (value === option.key ? key : value))
                                    ),
                                })
                            }}
                            suffix={
                                showKeys && option.key ? (
                                    <code className="text-xs text-secondary">{`returns '${option.key}'`}</code>
                                ) : undefined
                            }
                            data-attr="llma-evaluation-create-category-label"
                        />
                    </Tooltip>
                    <LemonButton
                        icon={<IconTrash />}
                        size="small"
                        tooltip="Remove category"
                        aria-label={`Remove category ${option.label || index + 1}`}
                        onClick={() =>
                            onChange({
                                options: options.filter((_, i) => i !== index),
                                passing_rule: withPassing(passing.filter((value) => value !== option.key)),
                            })
                        }
                    />
                </div>
            ))}
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    disabledReason={
                        options.length >= MAX_CATEGORICAL_OPTIONS
                            ? `You can add up to ${MAX_CATEGORICAL_OPTIONS} categories.`
                            : undefined
                    }
                    onClick={() => onChange({ options: [...options, { key: '', label: '' }] })}
                    data-attr="llma-evaluation-create-category-add"
                >
                    Add category
                </LemonButton>
            </div>
            {named.length > 0 && (
                <div className="flex flex-col gap-1 pt-2">
                    <span className="text-sm font-semibold">Which ones count as a pass?</span>
                    <div className="flex flex-wrap gap-1">
                        {named.map((option, index) => {
                            const passes = passing.includes(option.key)
                            return (
                                <LemonButton
                                    // Index too, because two categories can share a key until the duplicate is fixed.
                                    key={`${index}-${option.key}`}
                                    type="secondary"
                                    size="small"
                                    active={passes}
                                    icon={passes ? <IconCheck /> : undefined}
                                    onClick={() =>
                                        onChange({
                                            passing_rule: withPassing(
                                                passes
                                                    ? passing.filter((value) => value !== option.key)
                                                    : [...passing, option.key]
                                            ),
                                        })
                                    }
                                    data-attr="llma-evaluation-create-category-pass"
                                >
                                    {option.label}
                                </LemonButton>
                            )
                        })}
                    </div>
                    <span className="text-xs text-secondary">
                        {passing.length > 0
                            ? 'Runs with any other category fail. Pass rates and reports use this.'
                            : keepsEmptyRule
                              ? 'With none picked, only runs with no category pass. Pass rates and reports use this.'
                              : 'With none picked, runs only get a category, with no pass rate or reports.'}
                    </span>
                </div>
            )}
        </div>
    )
}
