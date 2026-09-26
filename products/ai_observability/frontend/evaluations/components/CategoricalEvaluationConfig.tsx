import { useId } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { categoricalOutputConfigError } from '../constants'
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
    const error = categoricalOutputConfigError(config)
    return (
        <div className="space-y-4">
            {error && <LemonBanner type="error">{error}</LemonBanner>}
            <LemonField.Pure label="Selection" htmlFor={`${id}-selection`}>
                <LemonSelect
                    id={`${id}-selection`}
                    value={config.selection_mode ?? 'single'}
                    options={[
                        { value: 'single', label: 'One category' },
                        { value: 'multiple', label: 'Multiple categories' },
                    ]}
                    onChange={(selection_mode) => onChange({ selection_mode })}
                />
            </LemonField.Pure>
            <div className="space-y-2">
                {options.map((option, index) => (
                    <div key={index} className="flex flex-wrap items-end gap-2">
                        <LemonField.Pure label="Label" htmlFor={`${id}-label-${index}`}>
                            <LemonInput
                                id={`${id}-label-${index}`}
                                value={option.label}
                                maxLength={256}
                                onChange={(label) =>
                                    onChange({
                                        options: options.map((item, i) => (i === index ? { ...item, label } : item)),
                                    })
                                }
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Key" htmlFor={`${id}-key-${index}`}>
                            <LemonInput
                                id={`${id}-key-${index}`}
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
                        </LemonField.Pure>
                        <LemonButton
                            icon={<IconTrash />}
                            aria-label={`Remove category ${option.label || index + 1}`}
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
                <LemonButton onClick={() => onChange({ options: [...options, { key: '', label: '' }] })}>
                    Add category
                </LemonButton>
                <p className="text-muted text-sm">
                    Results store category keys. Keep keys unchanged to preserve historical results.
                </p>
            </div>
            <LemonSwitch
                label="Allow N/A responses"
                checked={config.allows_na ?? false}
                onChange={(allows_na) => onChange({ allows_na })}
            />
            <LemonSwitch
                label="Set a passing rule"
                checked={!!rule}
                onChange={(enabled) => onChange({ passing_rule: enabled ? { categories: [] } : null })}
            />
            {rule ? (
                <div className="space-y-2">
                    <div className="font-semibold">Passing categories</div>
                    {options
                        .filter((option) => option.key)
                        .map((option, index) => (
                            <LemonCheckbox
                                key={index}
                                label={option.label || option.key}
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
                    <p className="text-muted text-sm">
                        Every returned category must be marked as passing.
                        {config.selection_mode === 'multiple' ? ' An empty selection passes.' : ''} Changing this rule
                        also updates how historical results count as passes.
                    </p>
                </div>
            ) : (
                <p className="text-muted text-sm">
                    Results stay neutral without a passing rule. Add a rule to enable pass rates and reports.
                </p>
            )}
        </div>
    )
}
