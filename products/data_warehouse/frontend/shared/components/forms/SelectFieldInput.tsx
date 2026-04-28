import { useEffect } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { SourceFieldSelectConfig } from '~/queries/schema/schema-general'

export interface SelectFieldInputProps {
    field: SourceFieldSelectConfig
    value: any
    onChange: (value: string) => void
    lastValue?: any
    renderOptionFields: () => JSX.Element
}

// Seeds the kea-forms state with `field.defaultValue` on mount when the form
// state value is undefined. Without this, the LemonSelect would render the
// default only visually (via the `||` fallback), and submit-time validation
// — which reads the underlying form state — would flag the still-undefined
// field as required.
export function SelectFieldInput({
    field,
    value,
    onChange,
    lastValue,
    renderOptionFields,
}: SelectFieldInputProps): JSX.Element {
    useEffect(() => {
        if (value !== undefined && value !== null && value !== '') {
            return
        }
        const seed = lastValue?.[field.name] || field.defaultValue
        if (seed !== undefined && seed !== null && seed !== '') {
            onChange(seed)
        }
        // Only seed once per mount — subsequent changes come from user interaction.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const displayValue = (value === undefined || value === null ? lastValue?.[field.name] : value) || field.defaultValue

    return (
        <>
            <LemonSelect options={field.options} value={displayValue} onChange={onChange} />
            {renderOptionFields()}
        </>
    )
}
