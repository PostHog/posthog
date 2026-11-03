import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { FeatureFlagRulesV2ReturnType, JsonType } from '~/types'

import { RULES_V2_NO_VALUE_TOOLTIP } from 'products/feature_flags/frontend/RulesV2Flow'

const BOOLEAN_OPTIONS = [
    { value: 'true', label: 'true' },
    { value: 'false', label: 'false' },
]

const NO_VALUE_OPTION = {
    value: 'null',
    label: 'No value',
    tooltip: RULES_V2_NO_VALUE_TOOLTIP,
}

/** A value of the flag's return type. A nullable string value is null while its input is empty. */
export function RulesV2ValueInput({
    returnType,
    value,
    onChange,
    nullable = false,
    id,
    className,
    'aria-label': ariaLabel,
    'data-attr': dataAttr,
}: {
    returnType: FeatureFlagRulesV2ReturnType
    value: JsonType | null
    onChange: (value: JsonType | null) => void
    nullable?: boolean
    id?: string
    className?: string
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
                placeholder={nullable ? 'No value' : 'Value to serve'}
                className={`ph-ignore-input font-mono ${className ?? ''}`}
                size="small"
                autoComplete="off"
                spellCheck={false}
                data-attr={dataAttr}
            />
        )
    }
    // LemonSegmentedButton drops these props, so a labelled group carries them.
    return (
        <div role="group" id={id} aria-label={ariaLabel} data-attr={dataAttr} className={className}>
            <LemonSegmentedButton
                size="small"
                value={String(value)}
                onChange={(option) => onChange(option === 'null' ? null : option === 'true')}
                options={nullable ? [...BOOLEAN_OPTIONS, NO_VALUE_OPTION] : BOOLEAN_OPTIONS}
            />
        </div>
    )
}
