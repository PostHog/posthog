import clsx from 'clsx'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

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
            {options.map((option) => {
                const content = (
                    <label
                        key={option.value}
                        className={clsx(
                            'flex items-center space-x-2',
                            option.disabledReason ? 'text-muted cursor-not-allowed' : 'cursor-pointer'
                        )}
                    >
                        <input
                            type="radio"
                            checked={option.value === value}
                            value={option.value}
                            onChange={() => {
                                if (!option.disabledReason) {
                                    onChange(option.value)
                                }
                            }}
                            disabled={!!option.disabledReason}
                        />
                        <span>{option.label}</span>
                    </label>
                )

                if (option.disabledReason) {
                    return (
                        <Tooltip key={option.value} title={option.disabledReason}>
                            {content}
                        </Tooltip>
                    )
                }
                return content
            })}
        </div>
    )
}
