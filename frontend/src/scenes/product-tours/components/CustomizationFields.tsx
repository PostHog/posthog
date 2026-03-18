import { IconX } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonColorPicker } from 'lib/lemon-ui/LemonColor/LemonColorPicker'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { WEB_SAFE_FONTS } from 'scenes/surveys/constants'

export const COLOR_PRESETS = [
    '#ffffff',
    '#1d1f27',
    '#1d4aff',
    '#f3f4f6',
    '#e5e7eb',
    '#ef4444',
    '#22c55e',
    '#f59e0b',
    '#8b5cf6',
    '#ec4899',
]

export const BOX_SHADOW_PRESETS = [
    { value: 'none', label: 'None' },
    { value: '0 2px 8px rgba(0, 0, 0, 0.1)', label: 'Subtle' },
    { value: '0 4px 12px rgba(0, 0, 0, 0.15)', label: 'Medium' },
    { value: '0 8px 24px rgba(0, 0, 0, 0.2)', label: 'Large' },
    { value: '0 12px 32px rgba(0, 0, 0, 0.25)', label: 'Extra large' },
]

export function ColorPickerField({
    label,
    value,
    onChange,
    showNone = false,
}: {
    label: string
    value: string | undefined
    onChange: (color: string) => void
    showNone?: boolean
}): JSX.Element {
    const isNone = value === 'transparent'
    const displayValue = isNone ? 'None' : value

    return (
        <LemonField.Pure label={label} className="flex-1">
            <div className="flex items-center gap-2">
                <LemonColorPicker
                    colors={COLOR_PRESETS}
                    selectedColor={isNone ? null : value}
                    onSelectColor={onChange}
                    showCustomColor
                />
                <span className="text-xs text-secondary font-mono">{displayValue}</span>
                {showNone && (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        icon={<IconX />}
                        onClick={() => onChange('transparent')}
                    />
                )}
            </div>
        </LemonField.Pure>
    )
}

export function FontSelector({
    value,
    onChange,
}: {
    value: string | undefined
    onChange: (font: string) => void
}): JSX.Element {
    return (
        <LemonField.Pure label="Font">
            <LemonSelect
                value={value}
                onChange={(font) => onChange(font || 'system-ui')}
                options={WEB_SAFE_FONTS.map((font) => ({
                    label: (
                        <span style={{ fontFamily: font.value === 'inherit' ? undefined : font.value }}>
                            {font.label}
                        </span>
                    ),
                    value: font.value,
                }))}
            />
        </LemonField.Pure>
    )
}

export function BoxShadowSelector({
    value,
    onChange,
}: {
    value: string | undefined
    onChange: (shadow: string) => void
}): JSX.Element {
    return (
        <LemonField.Pure label="Drop shadow">
            <LemonSelect
                value={value}
                onChange={(shadow) => onChange(shadow || '0 4px 12px rgba(0, 0, 0, 0.15)')}
                options={BOX_SHADOW_PRESETS}
            />
        </LemonField.Pure>
    )
}
