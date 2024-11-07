import { LemonButton, LemonLabel, LemonSegmentedButton } from '@posthog/lemon-ui'
import { useLocalStorage } from '@uidotdev/usehooks'
import { useActions, useValues } from 'kea'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { useState } from 'react'
import { userLogic } from 'scenes/userLogic'

const DEFAULT_CUSTOM_THEME_CONFIG = `body {
    --bg-3000: var(--bg-3000);
    --bg-light: var(--bg-light);
    --primary-alt-highlight: var(--primary-alt-highlight);
    --primary-alt: var(--primary-alt);
    --text-3000: var(--text-3000);
    --muted-3000: var(--muted-3000);
    --radius: var(--radius);
}`

export function CustomThemeSettings(): JSX.Element {
    const { user } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    const [customThemeConfig, setCustomThemeConfig] = useLocalStorage('CUSTOM_THEME_CONFIG', '')

    const [localCustomThemeConfig, setLocalCustomThemeConfig] = useState(
        customThemeConfig ? customThemeConfig : DEFAULT_CUSTOM_THEME_CONFIG
    )

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
                    <CodeEditor
                        className="border"
                        language="css"
                        value={localCustomThemeConfig}
                        onChange={(v) => {
                            setLocalCustomThemeConfig(v ?? '')
                        }}
                        height={400}
                        options={{
                            minimap: {
                                enabled: false,
                            },
                        }}
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
