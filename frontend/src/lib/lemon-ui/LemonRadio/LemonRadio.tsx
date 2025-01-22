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
    size?: 'sm' | 'base' | 'lg'
}

/** Single choice radio. */
export function LemonRadio<T extends React.Key>({
    value: selectedValue,
    onChange,
    options,
    className,
    radioPosition,
    size = 'sm',
}: LemonRadioProps<T>): JSX.Element {
    return (
        <div className={clsx('flex flex-col gap-2 font-medium', className)}>
            {options.map(({ value, label, disabledReason, description, ...optionProps }) => {
                const content = (
                    <label
                        key={value}
                        className={clsx(
                            'grid items-center gap-x-2 grid-cols-[min-content_auto] text-sm',
                            disabledReason ? 'text-muted cursor-not-allowed' : 'cursor-pointer',
                            {
                                'items-baseline': radioPosition === 'top',
                                'items-center': radioPosition === 'center' || !radioPosition,
                            }
                        )}
                        onClick={() => {
                            if (!disabledReason) {
                                onChange(value)
                            }
                        }}
                    >
                        <div
                            className={clsx(
                                size === 'sm' ? 'size-3' : size === 'lg' ? 'size-5' : 'size-4',
                                'rounded-full border-2 flex items-center justify-center',
                                disabledReason
                                    ? 'border-muted bg-muted/10'
                                    : value === selectedValue
                                    ? 'border-accent-primary bg-accent-primary'
                                    : 'border-border hover:border-accent-primary'
                            )}
                            {...optionProps}
                        >
                            {value === selectedValue && (
                                <div
                                    className={clsx(
                                        size === 'sm' ? 'size-1.5' : size === 'lg' ? 'size-2.5' : 'size-2',
                                        'rounded-full bg-white'
                                    )}
                                />
                            )}
                        </div>
                        <span>{label}</span>
                        {description && (
                            <div className="text-muted row-start-2 col-start-2 text-pretty">{description}</div>
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
