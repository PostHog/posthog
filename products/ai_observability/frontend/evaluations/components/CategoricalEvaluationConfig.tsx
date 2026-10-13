import { useId } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSelect, LemonSwitch, LemonTable } from '@posthog/lemon-ui'

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
    const id = useId()
    const options = config.options ?? []
    const rule = config.passing_rule && 'categories' in config.passing_rule ? config.passing_rule : null
    return (
        <div className="space-y-4">
            <LemonField.Pure
                label="Categories per result"
                htmlFor={`${id}-selection`}
                help="Choose whether each result can contain one category or several."
            >
                <LemonSelect
                    id={`${id}-selection`}
                    data-attr="llma-evaluation-categorical-selection"
                    value={config.selection_mode ?? 'single'}
                    options={[
                        { value: 'single', label: 'One category' },
                        { value: 'multiple', label: 'Multiple categories' },
                    ]}
                    onChange={(selection_mode) => onChange({ selection_mode })}
                />
            </LemonField.Pure>
            <LemonField.Pure label="Categories" error={categoricalOptionsError(config)}>
                <LemonTable
                    dataSource={options}
                    size="small"
                    embedded
                    stealth
                    inset
                    tableLayout="fixed"
                    uppercaseHeader={false}
                    emptyState="Add a category to define the possible results."
                    columns={[
                        {
                            title: 'Label',
                            key: 'label',
                            render: (_, option, index) => (
                                <LemonInput
                                    aria-label={`Category ${index + 1} label`}
                                    data-attr="llma-evaluation-categorical-label"
                                    placeholder="Resolved"
                                    fullWidth
                                    value={option.label}
                                    maxLength={256}
                                    onChange={(label) =>
                                        onChange({
                                            options: options.map((item, i) =>
                                                i === index ? { ...item, label } : item
                                            ),
                                        })
                                    }
                                />
                            ),
                        },
                        {
                            title: 'Key',
                            key: 'key',
                            render: (_, option, index) => (
                                <LemonInput
                                    aria-label={`Category ${index + 1} key`}
                                    data-attr="llma-evaluation-categorical-key"
                                    placeholder="resolved"
                                    fullWidth
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
                            ),
                        },
                        {
                            key: 'actions',
                            width: 48,
                            render: (_, option, index) => (
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
                                                          categories: rule.categories.filter(
                                                              (key) => key !== option.key
                                                          ),
                                                      },
                                                  }
                                                : {}),
                                        })
                                    }
                                />
                            ),
                        },
                    ]}
                />
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    className="self-start"
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
            </LemonField.Pure>
            <p className="text-muted text-sm">
                Results store category keys. Keep keys unchanged to preserve historical results.
            </p>
            <LemonSwitch
                label="Allow N/A responses"
                data-attr="llma-evaluation-categorical-allows-na"
                checked={config.allows_na ?? false}
                onChange={(allows_na) => onChange({ allows_na })}
            />
            <LemonField.Pure error={categoricalPassingRuleError(config)}>
                <LemonSwitch
                    label="Set a passing rule"
                    data-attr="llma-evaluation-categorical-passing-rule"
                    checked={!!rule}
                    onChange={(enabled) => onChange({ passing_rule: enabled ? { categories: [] } : null })}
                />
                {rule && (
                    <LemonField.Pure label="Passing categories" className="mt-2">
                        {options
                            .filter((option) => option.key)
                            .map((option, index) => (
                                <LemonCheckbox
                                    key={index}
                                    label={option.label || option.key}
                                    data-attr="llma-evaluation-categorical-passing-category"
                                    checked={rule.categories.includes(option.key)}
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
                            ))}
                    </LemonField.Pure>
                )}
            </LemonField.Pure>
            {rule ? (
                <p className="text-muted text-sm">
                    Every returned category must be marked as passing.
                    {config.selection_mode === 'multiple'
                        ? ' An empty selection passes only when no categories are marked as passing.'
                        : ''}{' '}
                    Changing this rule also updates how historical results count as passes.
                </p>
            ) : (
                <p className="text-muted text-sm">
                    Results show their categories without a pass or fail status. Add a passing rule to enable pass rates
                    and reports.
                </p>
            )}
        </div>
    )
}
