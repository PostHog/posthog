import clsx from 'clsx'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

export interface LemonRadioOption<T extends React.Key> {
    label: string | JSX.Element
    description?: string | JSX.Element
    value: T
    disabledReason?: string
    'data-attr'?: string
    'aria-label'?: string
}

export interface LemonRadioProps<T extends React.Key> {
    value?: T
    onChange: (newValue: T) => void
    options: LemonRadioOption<T>[]
    className?: string
    radioPosition?: 'center' | 'top'
    orientation?: 'vertical' | 'horizontal'
}

/** Single choice radio. */
export function LemonRadio<T extends React.Key>({
    value: selectedValue,
    onChange,
    options,
    className,
    radioPosition,
    orientation = 'vertical',
}: LemonRadioProps<T>): JSX.Element {
    return (
        <div
            className={clsx(
                'flex font-medium',
                orientation === 'vertical' ? 'flex-col gap-2' : 'flex-row gap-4',
                className
            )}
        >
            {options.map(({ value, label, disabledReason, description, ...optionProps }) => {
                const content = (
                    <label
                        key={value}
                        className={clsx(
                            'grid items-center gap-x-2 grid-cols-[min-content_auto] text-sm',
                            disabledReason ? 'text-secondary cursor-not-allowed' : 'cursor-pointer',
                            {
                                'items-baseline': radioPosition === 'top',
                                'items-center': radioPosition === 'center' || !radioPosition,
                            }
                        )}
                    >
                        <input
                            type="radio"
                            className="cursor-pointer"
                            checked={value === selectedValue}
                            value={value}
                            onChange={() => {
                                if (!disabledReason) {
                                    onChange(value)
                                }
                            }}
                            disabled={!!disabledReason}
                            {...optionProps}
                        />
                        <span>{label}</span>
                        {description && (
                            <div className="text-secondary row-start-2 col-start-2 text-pretty">{description}</div>
                        )}
                    </label>
                )

                if (disabledReason) {
                    return (
                        <Tooltip key={value} title={disabledReason}>
                            {content}
                        </Tooltip>
                    )
                }
                return content
            })}
        </div>
    )
}
