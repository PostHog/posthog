import { LemonCheckbox } from '@posthog/lemon-ui'

import type { EvaluationOutputConfig } from '../types'

export function EvaluationCategoryPassing({
    config,
    onChange,
}: {
    config: EvaluationOutputConfig
    onChange: (patch: EvaluationOutputConfig) => void
}): JSX.Element {
    // Rows that share a key are one category to the passing rule, so each key gets one checkbox.
    const options = (config.options ?? []).filter(
        (option, index, all) => option.key && all.findIndex((item) => item.key === option.key) === index
    )
    const passing = config.passing_rule && 'categories' in config.passing_rule ? config.passing_rule.categories : []
    const grades = !!config.passing_rule

    return (
        <div className="flex flex-col gap-2">
            <LemonCheckbox
                label="Track a pass rate"
                checked={grades}
                onChange={(on) => onChange({ passing_rule: on ? { categories: passing } : null })}
                data-attr="llma-evaluation-create-category-grading"
            />
            {grades && (
                <div className="flex flex-col gap-1 pl-6">
                    <span className="text-sm text-secondary">Passing categories</span>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                        {options.map((option) => (
                            <LemonCheckbox
                                key={option.key}
                                label={option.label}
                                checked={passing.includes(option.key)}
                                onChange={(on) =>
                                    onChange({
                                        passing_rule: {
                                            categories: on
                                                ? [...passing, option.key]
                                                : passing.filter((value) => value !== option.key),
                                        },
                                    })
                                }
                                data-attr="llma-evaluation-create-category-pass"
                            />
                        ))}
                    </div>
                    <span className="text-xs text-secondary">
                        {passing.length > 0
                            ? 'Runs with any other category fail.'
                            : config.selection_mode === 'multiple'
                              ? 'With none marked, only runs with no category pass.'
                              : 'Mark at least one category that passes.'}
                    </span>
                </div>
            )}
        </div>
    )
}
