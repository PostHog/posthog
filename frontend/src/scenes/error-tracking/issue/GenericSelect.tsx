import { LemonSelect } from '@posthog/lemon-ui'

export function GenericSelect<T extends string | number | boolean | null>({
    current,
    size,
    onChange,
    values,
    placeholder,
    renderValue,
}: {
    current: T | undefined
    size?: 'xsmall' | 'small' | 'medium' | 'large'
    onChange: (value: T) => void
    values: T[]
    placeholder?: string
    renderValue: (key: T) => string | JSX.Element
}): JSX.Element {
    return (
        <LemonSelect
            onChange={onChange}
            value={current}
            placeholder={placeholder}
            options={values.map((key) => ({
                value: key,
                label: renderValue(key),
            }))}
            size={size}
        />
    )
}
