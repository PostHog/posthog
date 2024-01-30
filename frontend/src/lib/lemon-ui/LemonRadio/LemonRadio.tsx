import clsx from 'clsx'

import { IconCheckmark, IconRadioButtonUnchecked } from '../icons'

export interface LemonRadioOption<T extends React.Key> {
    label: string | JSX.Element
    value: T
}

export interface LemonRadioProps<T extends React.Key> {
    value?: T
    onChange: (newValue: T) => void
    options: LemonRadioOption<T>[]
    disabled?: boolean
    fullWidth?: boolean
}

/** Single choice radio. */
export function LemonRadio<T extends React.Key>({
    value,
    onChange,
    options,
    disabled,
    fullWidth,
}: LemonRadioProps<T>): JSX.Element {
    return (
        <div
            className={clsx('flex flex-col gap-2', fullWidth && 'w-full', disabled && 'text-muted cursor-not-allowed')}
        >
            {options.map((option) => (
                <div
                    key={option.value}
                    className={clsx('flex items-center space-x-1', !disabled && 'cursor-pointer')}
                    onClick={() => !disabled && onChange(option.value)}
                >
                    {option.value === value ? (
                        <IconCheckmark className={clsx('text-lg', !disabled && 'text-primary-3000')} />
                    ) : (
                        <IconRadioButtonUnchecked className={clsx('text-lg', !disabled && 'hover:text-primary-3000')} />
                    )}
                    <span>{option.label}</span>
                </div>
            ))}
        </div>
    )
}
