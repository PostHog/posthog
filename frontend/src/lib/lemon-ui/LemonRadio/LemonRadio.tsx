import clsx from 'clsx'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export interface LemonRadioOption<T extends React.Key> {
    label: string | JSX.Element
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
}

/** Single choice radio. */
export function LemonRadio<T extends React.Key>({
    value: selectedValue,
    onChange,
    options,
    className,
}: LemonRadioProps<T>): JSX.Element {
    return (
        <div className={clsx('flex flex-col gap-2 font-medium', className)}>
            {options.map(({ value, label, disabledReason, ...optionProps }) => {
                const content = (
                    <label
                        key={value}
                        className={clsx(
                            'flex items-center space-x-2',
                            disabledReason ? 'text-muted cursor-not-allowed' : 'cursor-pointer'
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
