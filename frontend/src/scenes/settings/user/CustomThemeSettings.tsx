import { LemonButton, LemonLabel, LemonSegmentedButton } from '@posthog/lemon-ui'
import { useLocalStorage } from '@uidotdev/usehooks'
import { useActions, useValues } from 'kea'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { useState } from 'react'
import { userLogic } from 'scenes/userLogic'

import { ColorPickerButton } from '~/queries/nodes/DataVisualization/Components/ColorPickerButton'

type CustomThemeConfig = {
    'bg-3000': string
    'bg-light': string
    'primary-alt-highlight': string
    'primary-alt': string
    'text-3000': string
    'muted-3000': string
    radius: string
}

const DEFAULT_CUSTOM_THEME_CONFIG = {
    'bg-3000': 'var(--bg-3000)',
    'bg-light': 'var(--bg-light)',
    'primary-alt-highlight': 'var(--primary-alt-highlight)',
    'primary-alt': 'var(--primary-alt)',
    'text-3000': 'var(--text-3000)',
    'muted-3000': 'var(--muted-3000)',
    radius: 'var(--radius)',
}

export function CustomThemeSettings(): JSX.Element {
    const { user } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    const [customThemeConfig, setCustomThemeConfig] = useLocalStorage<CustomThemeConfig | null>(
        'CUSTOM_THEME_CONFIG',
        null
    )

    const [localCustomThemeConfig, setLocalCustomThemeConfig] = useState<CustomThemeConfig>(DEFAULT_CUSTOM_THEME_CONFIG)

    const onChange = (changes: Partial<CustomThemeConfig>): void => {
        setLocalCustomThemeConfig({ ...DEFAULT_CUSTOM_THEME_CONFIG, ...customThemeConfig, ...changes })
    }

    return (
        <>
            <div className="flex flex-col space-y-4">
                <LemonLabel>Choose a base theme</LemonLabel>
                <LemonSegmentedButton
                    onChange={(value) => {
                        if (confirm('Chaning the default theme will reset custom colors')) {
                            updateUser({ theme_mode: value })
                        }
                    }}
                    value={user?.theme_mode || 'light'}
                    options={[
                        {
                            value: 'light',
                            label: 'Light',
                        },
                        {
                            value: 'dark',
                            label: 'Dark',
                        },
                    ]}
                    fullWidth
                />
                <div className="flex space-x-2">
                    <LemonLabel>Background color</LemonLabel>
                    <ColorPickerButton
                        color={localCustomThemeConfig['bg-3000']}
                        onColorSelect={(value) => onChange({ 'bg-3000': value })}
                    >
                        Default
                    </ColorPickerButton>
                    <ColorPickerButton color={localCustomThemeConfig['bg-3000']}>Hover</ColorPickerButton>
                </div>
                <div className="flex space-x-2">
                    <LemonLabel>Radius</LemonLabel>
                    <LemonSlider
                        min={0}
                        max={1}
                        step={0.125}
                        value={Number(localCustomThemeConfig['radius'])}
                        onChange={(value) => onChange({ radius: String(value) })}
                        className="flex-1"
                    />
                </div>
                <div className="flex space-x-1">
                    <LemonButton type="primary" onClick={() => setCustomThemeConfig(localCustomThemeConfig)}>
                        Save
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            setCustomThemeConfig(DEFAULT_CUSTOM_THEME_CONFIG)
                            setLocalCustomThemeConfig(DEFAULT_CUSTOM_THEME_CONFIG)
                        }}
                    >
                        Reset
                    </LemonButton>
                </div>
            </div>
        </>
    )
}
