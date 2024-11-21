import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { urls } from '../urls'

export const scene: SceneExport = {
    component: CustomCssScene,
}

const TRON_THEME = `
:root {
    --radius: 0px;
}

body[theme=dark] {
    --border: rgba(0, 255, 1, 0.5);
    --link: #00FF01;
    --border-bold: #00FF01;
    --bg-3000: #111;
    --glass-bg-3000: #111;
    --bg-light: #222;
    --bg-table: #222;
    --muted-3000: #0EA70E;
    --primary-3000: #00FF01;
    --primary-3000-hover: #00FF01;
    --primary-alt-highlight: rgba(0, 255, 1, 0.1);
    --text-3000: #00FF01;
    --accent-3000: #222;
    --glass-border-3000: rgba(0,0,0,.3);
    --font-title: ui-monospace, 'Cascadia Code', 'Source Code Pro', Menlo, Consolas, 'DejaVu Sans Mono', monospace;

    --primary-3000-frame-bg-light: #00FF01;
    --primary-3000-button-bg: #00FF01;
    --primary-3000-button-border: #00FF01;
    --text-secondary-3000: #00FF01;
}

.TopBar3000__content {
	border-bottom: solid 1px #00FF01;
}
`

export function CustomCssScene(): JSX.Element {
    const { persistedCustomCss, previewingCustomCss } = useValues(themeLogic)
    const { saveCustomCss, setPreviewingCustomCss } = useActions(themeLogic)

    useEffect(() => {
        setPreviewingCustomCss(previewingCustomCss || persistedCustomCss || '')
    }, [])

    const onPreview = (): void => {
        router.actions.push(urls.projectHomepage())
    }

    return (
        <div className="flex flex-col space-y-2">
            <PageHeader
                buttons={
                    <>
                        <LemonButton type="secondary" onClick={onPreview}>
                            Preview
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                saveCustomCss()
                                router.actions.push(urls.projectHomepage())
                            }}
                        >
                            Save and set
                        </LemonButton>
                    </>
                }
            />
            <p>
                You can add custom CSS to change the style of your PostHog instance. If you need some inspiration try
                our templates: <Link onClick={() => setPreviewingCustomCss(TRON_THEME)}>Tron</Link>
            </p>
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
        </div>
    )
}
