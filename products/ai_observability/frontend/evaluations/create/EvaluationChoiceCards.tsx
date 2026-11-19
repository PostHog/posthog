import { IconCheckCircle } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

export interface EvaluationChoice<T extends string> {
    value: T
    label: string
    description: string
    icon: JSX.Element
    disabledReason?: string
}

export function EvaluationChoiceCards<T extends string>({
    label,
    value,
    options,
    onChange,
    dataAttr,
    stacked = false,
}: {
    label: string
    value: T
    options: EvaluationChoice<T>[]
    onChange: (value: T) => void
    dataAttr: string
    /** One card per row, for a narrow column next to other content. */
    stacked?: boolean
}): JSX.Element {
    return (
        <div
            role="radiogroup"
            aria-label={label}
            className={cn('grid grid-cols-1 gap-2', !stacked && '@min-[40rem]/evaluation:grid-cols-2')}
            data-attr={dataAttr}
        >
            {options.map((option) => {
                const selected = option.value === value
                return (
                    <Tooltip key={option.value} title={option.disabledReason} openOnClick>
                        <button
                            type="button"
                            role="radio"
                            aria-checked={selected}
                            // aria-disabled, not disabled, so the card stays focusable and its tooltip can say why.
                            aria-disabled={!!option.disabledReason}
                            onClick={() => {
                                if (!option.disabledReason) {
                                    onChange(option.value)
                                }
                            }}
                            className={cn(
                                'flex items-start gap-3 rounded p-3 text-left transition-colors motion-reduce:transition-none',
                                selected
                                    ? 'border-2 border-accent bg-accent-highlight-light'
                                    : 'border border-primary bg-surface-primary hover:bg-fill-button-tertiary-hover',
                                option.disabledReason ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
                            )}
                            data-attr={`${dataAttr}-${option.value}`}
                        >
                            <span className="text-lg text-secondary shrink-0 mt-0.5">{option.icon}</span>
                            <span className="flex flex-col gap-0.5 min-w-0 flex-1">
                                <span className="text-sm font-semibold">{option.label}</span>
                                <span className="text-xs text-secondary">{option.description}</span>
                            </span>
                            {selected && <IconCheckCircle className="text-accent text-base shrink-0" />}
                        </button>
                    </Tooltip>
                )
            })}
        </div>
    )
}
