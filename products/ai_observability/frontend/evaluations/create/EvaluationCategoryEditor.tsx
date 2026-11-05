import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { MAX_CATEGORICAL_OPTIONS } from '../constants'
import type { EvaluationOutputConfig } from '../types'
import { categoryKey } from './categoryKey'

/**
 * The categories of an evaluation. A new category's key follows its label. With grading on, the categories marked as a
 * pass are the passing rule; with it off, runs get a category and no pass or fail.
 */
export function EvaluationCategoryEditor({
    config,
    onChange,
    showKeys,
    storedKeys = [],
}: {
    config: EvaluationOutputConfig
    onChange: (patch: EvaluationOutputConfig) => void
    /** Code returns the key, so a code evaluation shows it next to each name. */
    showKeys: boolean
    /** Keys the saved evaluation already stores. Past results and code use them, so renaming keeps them. */
    storedKeys?: string[]
}): JSX.Element {
    const options = config.options ?? []
    const passing = config.passing_rule && 'categories' in config.passing_rule ? config.passing_rule.categories : []
    const named = options.filter((option) => option.key)
    const grades = !!config.passing_rule
    const withPassing = (keys: string[]): EvaluationOutputConfig['passing_rule'] =>
        grades ? { categories: keys } : null
    // Only the first row with a saved key keeps it. A new row whose label passes through a saved one keeps deriving.
    const keepsStoredKey = (key: string, index: number): boolean =>
        storedKeys.includes(key) && options.findIndex((item) => item.key === key) === index

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
                                const key = keepsStoredKey(option.key, index) ? option.key : categoryKey(label)
                                // While another row still holds the old key, its pass mark stays with that row.
                                const shared = options.some((item, i) => i !== index && item.key === option.key)
                                onChange({
                                    options: options.map((item, i) => (i === index ? { label, key } : item)),
                                    passing_rule: withPassing(
                                        shared ? passing : passing.map((value) => (value === option.key ? key : value))
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
                                // Another row with the same key keeps its pass mark.
                                passing_rule: withPassing(
                                    options.some((item, i) => i !== index && item.key === option.key)
                                        ? passing
                                        : passing.filter((value) => value !== option.key)
                                ),
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
                <div className="flex flex-col gap-2 pt-2">
                    <LemonSwitch
                        label="Grade runs as pass or fail"
                        checked={grades}
                        onChange={(on) => onChange({ passing_rule: on ? { categories: passing } : null })}
                        data-attr="llma-evaluation-create-category-grading"
                    />
                    {grades ? (
                        <div className="flex flex-col gap-1">
                            <span className="text-sm font-semibold">Which ones count as a pass?</span>
                            <div className="flex flex-wrap gap-1">
                                {named.map((option, index) => {
                                    const passes = passing.includes(option.key)
                                    return (
                                        <button
                                            key={`${index}-${option.key}`}
                                            type="button"
                                            aria-pressed={passes}
                                            className={cn(
                                                'rounded border px-2 py-1 text-sm cursor-pointer transition-colors',
                                                passes
                                                    ? 'bg-success-highlight border-success text-success font-semibold'
                                                    : 'bg-surface-primary hover:bg-fill-highlight-100'
                                            )}
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
                                        </button>
                                    )
                                })}
                            </div>
                            <span className="text-xs text-secondary">
                                {passing.length > 0
                                    ? 'Runs with any other category fail. Pass rates and reports use this.'
                                    : config.selection_mode === 'multiple'
                                      ? 'With none picked, only runs with no category pass.'
                                      : 'Pick at least one category that counts as a pass.'}
                            </span>
                        </div>
                    ) : (
                        <span className="text-xs text-secondary">
                            Runs only get a category, with no pass rate or reports.
                        </span>
                    )}
                </div>
            )}
        </div>
    )
}
