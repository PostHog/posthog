import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { MAX_CATEGORICAL_OPTIONS, categoricalOptionsError, categoricalPassingRuleError } from '../constants'
import type { EvaluationOutputConfig } from '../types'

export function CategoricalEvaluationConfig({
    config,
    onChange,
}: {
    config: EvaluationOutputConfig
    onChange: (patch: EvaluationOutputConfig) => void
}): JSX.Element {
    const options = config.options ?? []
    const rule = config.passing_rule && 'categories' in config.passing_rule ? config.passing_rule : null
    const updateOption = (index: number, patch: Partial<{ key: string; label: string }>): void =>
        onChange({ options: options.map((item, i) => (i === index ? { ...item, ...patch } : item)) })

    return (
        <div className="flex flex-col gap-4">
            <LemonField.Pure label="Categories per result">
                <LemonSegmentedButton
                    value={config.selection_mode ?? 'single'}
                    onChange={(selection_mode) => onChange({ selection_mode })}
                    options={[
                        { value: 'single', label: 'One category' },
                        { value: 'multiple', label: 'Several categories' },
                    ]}
                    fullWidth
                    data-attr="llma-evaluation-categorical-selection"
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Categories"
                error={categoricalOptionsError(config)}
                help="Results store the key. Keep a key unchanged to keep its past results."
            >
                <div className="flex flex-col gap-2">
                    {options.length === 0 && (
                        <span className="text-sm text-secondary">Add a category to define the possible results.</span>
                    )}
                    {options.map((option, index) => (
                        <div key={index} className="flex items-center gap-2">
                            <LemonInput
                                className="flex-1 min-w-0"
                                aria-label={`Category ${index + 1} label`}
                                data-attr="llma-evaluation-categorical-label"
                                placeholder="Label, for example Resolved"
                                value={option.label}
                                maxLength={256}
                                onChange={(label) => updateOption(index, { label })}
                            />
                            <LemonInput
                                className="w-36 shrink-0 font-mono"
                                aria-label={`Category ${index + 1} key`}
                                data-attr="llma-evaluation-categorical-key"
                                placeholder="key"
                                value={option.key}
                                maxLength={128}
                                onChange={(key) =>
                                    onChange({
                                        options: options.map((item, i) => (i === index ? { ...item, key } : item)),
                                        ...(rule
                                            ? {
                                                  passing_rule: {
                                                      categories: rule.categories.map((value) =>
                                                          value === option.key ? key : value
                                                      ),
                                                  },
                                              }
                                            : {}),
                                    })
                                }
                            />
                            {rule && (
                                <LemonCheckbox
                                    label="Passes"
                                    data-attr="llma-evaluation-categorical-passing-category"
                                    disabledReason={option.key ? undefined : 'Add a key first'}
                                    checked={!!option.key && rule.categories.includes(option.key)}
                                    onChange={(checked) =>
                                        onChange({
                                            passing_rule: {
                                                categories: checked
                                                    ? [...rule.categories, option.key]
                                                    : rule.categories.filter((key) => key !== option.key),
                                            },
                                        })
                                    }
                                />
                            )}
                            <LemonButton
                                icon={<IconTrash />}
                                size="small"
                                tooltip="Remove category"
                                aria-label={`Remove category ${option.label || index + 1}`}
                                data-attr="llma-evaluation-categorical-remove"
                                onClick={() =>
                                    onChange({
                                        options: options.filter((_, i) => i !== index),
                                        ...(rule
                                            ? {
                                                  passing_rule: {
                                                      categories: rule.categories.filter((key) => key !== option.key),
                                                  },
                                              }
                                            : {}),
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
                            data-attr="llma-evaluation-categorical-add"
                            disabledReason={
                                options.length >= MAX_CATEGORICAL_OPTIONS
                                    ? `You can add up to ${MAX_CATEGORICAL_OPTIONS} categories.`
                                    : undefined
                            }
                            onClick={() => onChange({ options: [...options, { key: '', label: '' }] })}
                        >
                            Add category
                        </LemonButton>
                    </div>
                </div>
            </LemonField.Pure>
            <LemonSwitch
                label="Allow N/A responses"
                data-attr="llma-evaluation-categorical-allows-na"
                checked={config.allows_na ?? false}
                onChange={(allows_na) => onChange({ allows_na })}
                bordered
                fullWidth
            />
            <LemonField.Pure
                error={categoricalPassingRuleError(config)}
                help={
                    rule
                        ? `A result passes when every category it returns is marked as passing.${
                              config.selection_mode === 'multiple'
                                  ? ' An empty selection passes only when no category is marked.'
                                  : ''
                          } Changing this also changes how past results count.`
                        : 'Without a passing rule, results show their categories but no pass rate or reports.'
                }
            >
                <LemonSwitch
                    label="Set a passing rule"
                    data-attr="llma-evaluation-categorical-passing-rule"
                    checked={!!rule}
                    onChange={(enabled) => onChange({ passing_rule: enabled ? { categories: [] } : null })}
                    bordered
                    fullWidth
                />
            </LemonField.Pure>
        </div>
    )
}
