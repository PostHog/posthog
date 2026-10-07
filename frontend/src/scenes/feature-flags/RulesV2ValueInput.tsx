import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { FeatureFlagRulesV2ReturnType, JsonType } from '~/types'

import { BOOLEAN_OPTIONS } from './featureFlagRulesV2EditorLogic'

/** A value of the flag's return type. A nullable string value is null while its input is empty. */
export function RulesV2ValueInput({
    returnType,
    value,
    onChange,
    nullable = false,
    id,
    'aria-label': ariaLabel,
    'data-attr': dataAttr,
}: {
    returnType: FeatureFlagRulesV2ReturnType
    value: JsonType | null
    onChange: (value: JsonType | null) => void
    nullable?: boolean
    id?: string
    'aria-label'?: string
    'data-attr'?: string
}): JSX.Element {
    if (returnType === 'string') {
        return (
            <LemonInput
                id={id}
                aria-label={ariaLabel}
                value={typeof value === 'string' ? value : ''}
                onChange={(text) => onChange(nullable && text === '' ? null : text)}
                placeholder={nullable ? 'null' : undefined}
                className="ph-ignore-input"
                autoComplete="off"
                spellCheck={false}
                data-attr={dataAttr}
            />
        )
    }
    return (
        <LemonSegmentedButton
            size="small"
            value={String(value)}
            onChange={(option) => onChange(option === 'null' ? null : option === 'true')}
            options={nullable ? [...BOOLEAN_OPTIONS, { value: 'null', label: 'null' }] : BOOLEAN_OPTIONS}
            data-attr={dataAttr}
        />
    )
}
