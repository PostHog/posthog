import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export const scene: SceneExport = {
    component: ThemeCreatorScene,
}

const DEFAULT_CUSTOM_THEME_CONFIG = `--bg-3000: var(--bg-3000);
--bg-light: var(--bg-light);
--primary-alt-highlight: var(--primary-alt-highlight);
--primary-alt: var(--primary-alt);
--text-3000: var(--text-3000);
--muted-3000: var(--muted-3000);
--radius: var(--radius);`

export function ThemeCreatorScene({ themeId }: { themeId: string }): JSX.Element {
    const { setCustomThemeId } = useActions(themeLogic)
    const [localCustomThemeConfig, setLocalCustomThemeConfig] = useState<string>(DEFAULT_CUSTOM_THEME_CONFIG)

    const onSave = (chooseTheme: boolean): void => {
        if (chooseTheme) {
            setCustomThemeId(themeId)
        }
    }

    return (
        <div className="flex space-x-2">
            <PageHeader
                buttons={
                    <>
                        <LemonButton type="secondary" onClick={() => onSave(false)}>
                            Save
                        </LemonButton>
                        <LemonButton type="primary" onClick={() => onSave(true)}>
                            Set and save
                        </LemonButton>
                    </>
                }
            />
            <CodeEditor
                className="border"
                language="css"
                value={localCustomThemeConfig}
                onChange={(v) => {
                    setLocalCustomThemeConfig(v ?? '')
                }}
                height={600}
                options={{
                    minimap: {
                        enabled: false,
                    },
                }}
            />
        </div>
    )
}
