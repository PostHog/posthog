import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconWrench } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { SceneExport } from 'scenes/sceneTypes'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { urls } from '../urls'

export const scene: SceneExport = {
    component: CustomCssScene,
}

const TRON_THEME = `:root {
    --radius: 0px;
}

body[theme=dark] {
    --border: rgba(0, 255, 1, 0.5);
    --link: #00FF01;
    --border-bold: #00FF01;
    --color-bg-3000: #111;
    --glass-bg-3000: #111;
    --color-bg-light: #222;
    --color-bg-table: #222;
    --muted-3000: #0EA70E;
    --primary-3000: #00FF01;
    --primary-3000-hover: #00FF01;
    --primary-alt-highlight: rgba(0, 255, 1, 0.1);
    --text-3000: #00FF01;
    --color-accent-3000: #222;
    --glass-border-3000: rgba(0,0,0,.3);
    --font-title: ui-monospace, 'Cascadia Code', 'Source Code Pro', Menlo, Consolas, 'DejaVu Sans Mono', monospace;

    --primary-3000-frame-bg-light: #00FF01;
    --primary-3000-button-bg: #00FF01;
    --primary-3000-button-border: #00FF01;
    --color-text-tertiary: #00FF01;
}

.TopBar3000__content {
	border-bottom: solid 1px #00FF01;
}`

const BARBIE_THEME = `:root {
    --radius: 16px;
}

body[theme=light] {
    --border: rgba(255, 105, 180, 0.5);
    --border-3000: #ff409f;
    --link: #E306AD;
    --border-bold: rgba(255, 105, 180, 0.8);
    --color-bg-3000: #FED9E9;
    --glass-bg-3000: rgba(255, 192, 203, 0.8);
    --color-bg-light: #FFF0F5;
    --color-bg-table: #F8BBD0;
    --muted-3000: #E306AD;
    --primary-3000: #FF69B4;
    --primary-3000-hover: #FF1493;
    --primary-alt-highlight: rgba(255, 105, 180, 0.1);
    --text-3000: #ed3993;
    --text-3000-light: #58003f;
    --color-accent-3000: #FEBDE2;
    --glass-border-3000: rgba(245, 145, 199, 0.3);

    --primary-3000-frame-bg-light: #F18DBC;
    --primary-3000-button-bg: #FF69B4;
    --primary-3000-button-border: #FF1493;
    --primary-3000-button-border-hover: #db097b;
    --color-text-tertiary: #FFB6C1;

    --secondary-3000-button-border: #FF1493;
    --secondary-3000-frame-bg-light: #F7B9D7;
    --secondary-3000-button-border-hover: #d40b76;
}`

export function CustomCssScene(): JSX.Element {
    const { persistedCustomCss, previewingCustomCss } = useValues(themeLogic)
    const { saveCustomCss, setPreviewingCustomCss } = useActions(themeLogic)

    useOnMountEffect(() => {
        setPreviewingCustomCss(previewingCustomCss || persistedCustomCss || '')
    })

    const onPreview = (): void => {
        router.actions.push(urls.projectRoot())
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Custom CSS"
                resourceType={{
                    type: 'customCss',
                    forceIcon: <IconWrench />,
                }}
                actions={
                    <>
                        <LemonButton type="secondary" onClick={onPreview} size="small">
                            Preview
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                saveCustomCss()
                                router.actions.push(urls.projectRoot())
                            }}
                            size="small"
                        >
                            Save and set
                        </LemonButton>
                    </>
                }
            />
            <p>
                You can add custom CSS to change the style of your PostHog instance. If you need some inspiration try
                our templates: <Link onClick={() => setPreviewingCustomCss(TRON_THEME)}>Tron</Link>,{' '}
                <Link onClick={() => setPreviewingCustomCss(BARBIE_THEME)}>Barbie</Link>
            </p>
            <SceneDivider />
            <CodeEditor
                className="border"
                language="css"
                value={previewingCustomCss || ''}
                onChange={(v) => setPreviewingCustomCss(v ?? null)}
                height={600}
                options={{
                    minimap: {
                        enabled: false,
                    },
                }}
            />
        </SceneContent>
    )
}
