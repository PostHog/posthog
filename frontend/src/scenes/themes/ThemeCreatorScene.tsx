import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { themeLogic, THEMES } from '~/layout/navigation-3000/themeLogic'

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

export function ThemeCreatorScene(): JSX.Element {
    const themeId = router.values.searchParams.id
    const { customThemes } = useValues(themeLogic)
    const { setCustomThemeId, setCustomTheme } = useActions(themeLogic)
    const [localCustomThemeStyles, setLocalCustomThemeStyles] = useState<string>(
        customThemes[themeId].styles ?? DEFAULT_CUSTOM_THEME_CONFIG
    )

    const onSave = (chooseTheme: boolean): void => {
        if (chooseTheme) {
            setCustomThemeId(themeId)
        }
        setCustomTheme(themeId, { ...THEMES[themeId], styles: localCustomThemeStyles })
        router.actions.push(urls.themeLibrary())
    }

    return (
        <div className="flex flex-col space-y-2">
            <PageHeader
                buttons={
                    <>
                        <LemonButton type="secondary" onClick={() => onSave(false)}>
                            Save and close
                        </LemonButton>
                        <LemonButton type="primary" onClick={() => onSave(true)}>
                            Save and set
                        </LemonButton>
                    </>
                }
            />
            <CodeEditor
                className="border"
                language="css"
                value={localCustomThemeStyles}
                onChange={(v) => {
                    setLocalCustomThemeStyles(v ?? '')
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
