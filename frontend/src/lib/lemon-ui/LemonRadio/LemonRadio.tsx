import clsx from 'clsx'

export interface LemonRadioOption<T extends React.Key> {
    label: string | JSX.Element
    value: T
    disabledReason?: string
}

export interface LemonRadioProps<T extends React.Key> {
    value?: T
    onChange: (newValue: T) => void
    options: LemonRadioOption<T>[]
    fullWidth?: boolean
}

/** Single choice radio. */
export function LemonRadio<T extends React.Key>({
    value,
    onChange,
    options,
    fullWidth,
}: LemonRadioProps<T>): JSX.Element {
    return (
        <div className={clsx('flex flex-col gap-2', fullWidth && 'w-full')}>
            {options.map((option) => (
                <div
                    key={option.value}
                    className={clsx(
                        'flex items-center space-x-1',
                        option.disabledReason ? 'text-muted cursor-not-allowed' : 'cursor-pointer'
                    )}
                    onClick={() => !!option.disabledReason && onChange(option.value)}
                >
                    <input
                        type="radio"
                        checked={option.value === value}
                        name={String(option.value)}
                        value={option.value}
                    />
                    <label htmlFor={String(option.value)}>{option.label}</label>
                    {/* {option.value === value ? (
                        <IconCheckmark className={clsx('text-lg', !disabled && 'text-primary-3000')} />
                    ) : (
                        <IconRadioButtonUnchecked className={clsx('text-lg', !disabled && 'hover:text-primary-3000')} />
                    )}
                    <span>{option.label}</span> */}
                </div>
            ))}
        </div>
    )
}
