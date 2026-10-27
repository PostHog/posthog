import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { FeatureFlagRulesV2ReturnType, JsonType } from '~/types'

const BOOLEAN_OPTIONS = [
    { value: 'true', label: 'true' },
    { value: 'false', label: 'false' },
]

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
                placeholder={nullable ? 'Leave empty for null' : undefined}
                className="ph-ignore-input"
                autoComplete="off"
                spellCheck={false}
                data-attr={dataAttr}
            />
        )
    }
    // LemonSegmentedButton drops these props, so a labelled group carries them.
    return (
        <div role="group" id={id} aria-label={ariaLabel} data-attr={dataAttr}>
            <LemonSegmentedButton
                size="small"
                value={String(value)}
                onChange={(option) => onChange(option === 'null' ? null : option === 'true')}
                options={nullable ? [...BOOLEAN_OPTIONS, { value: 'null', label: 'null' }] : BOOLEAN_OPTIONS}
            />
        </div>
    )
}
