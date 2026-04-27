import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { JsonType, FeatureFlagValueType } from '~/types'

import { JSONEditorInput } from './JSONEditorInput'

interface FeatureFlagValueInputProps {
    valueType: FeatureFlagValueType
    value: JsonType | undefined
    onChange: (value: JsonType) => void
    placeholder?: string
}

export function FeatureFlagValueInput({
    valueType,
    value,
    onChange,
    placeholder,
}: FeatureFlagValueInputProps): JSX.Element {
    if (valueType === FeatureFlagValueType.BOOLEAN) {
        return (
            <LemonSelect
                value={value === false ? 'false' : 'true'}
                onChange={(newValue) => onChange(newValue === 'true')}
                options={[
                    { label: 'True', value: 'true' },
                    { label: 'False', value: 'false' },
                ]}
                fullWidth
            />
        )
    }

    if (valueType === FeatureFlagValueType.STRING) {
        return (
            <LemonInput
                value={typeof value === 'string' ? value : ''}
                onChange={(newValue) => onChange(newValue)}
                placeholder={placeholder ?? 'Value returned by this flag'}
            />
        )
    }

    return (
        <JSONEditorInput
            value={value ?? {}}
            onChange={(newValue) => onChange(newValue ?? '')}
            placeholder={placeholder ?? '{"key": "value"}'}
        />
    )
}
