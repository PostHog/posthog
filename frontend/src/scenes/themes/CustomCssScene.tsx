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

const TRON_THEME = `:root {
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
    --text-tertiary: #00FF01;
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
    --bg-3000: #FED9E9;
    --glass-bg-3000: rgba(255, 192, 203, 0.8);
    --bg-light: #FFF0F5;
    --bg-table: #F8BBD0;
    --muted-3000: #E306AD;
    --primary-3000: #FF69B4;
    --primary-3000-hover: #FF1493;
    --primary-alt-highlight: rgba(255, 105, 180, 0.1);
    --text-3000: #ed3993;
    --text-3000-light: #58003f;
    --accent-3000: #FEBDE2;
    --glass-border-3000: rgba(245, 145, 199, 0.3);

    --primary-3000-frame-bg-light: #F18DBC;
    --primary-3000-button-bg: #FF69B4;
    --primary-3000-button-border: #FF1493;
    --primary-3000-button-border-hover: #db097b;
    --text-tertiary: #FFB6C1;

    --secondary-3000-button-border: #FF1493;
    --secondary-3000-frame-bg-light: #F7B9D7;
    --secondary-3000-button-border-hover: #d40b76;
}`

const LUMON_THEME = `:root {
    --radius: 0px;
    --font-mono: 'Courier New', Courier, monospace;

    --border: rgba(147, 196, 255, 0.5);
    --border-bold: #93C4FF;
    --link: #93C4FF;
    --text-3000: #93C4FF;
    --bg-3000: #000000;
    --bg-light: #1B2B3F;
    --bg-table: #1B2B3F;
    --muted-3000: #93C4FF;
    --primary-3000: #93C4FF;
    --primary-3000-hover: #93C4FF;
    --primary-alt-highlight: rgba(147, 196, 255, 0.1);
    --accent-3000: #1B2B3F;
    --glass-border-3000: rgba(0, 0, 0, 0.3);

    --primary-3000-frame-bg-light: #93C4FF;
    --primary-3000-button-bg: #93C4FF;
    --primary-3000-button-border: #93C4FF;
    --text-tertiary: #93C4FF;
    
    /* Override yellow warning colors */
    --warning: #93C4FF;
    --warning-highlight: #93C4FF;
    --warning-light: rgba(147, 196, 255, 0.1);
    --primary-light: rgba(147, 196, 255, 0.1);
    --primary-highlight: #93C4FF;
    --danger-highlight: #93C4FF;

    --terminal-glow: 0 0 10px rgba(147, 196, 255, 0.3);
}

body,
body[theme='dark'] {
    background-color: var(--bg-3000);
    color: var(--text-3000);
    font-family: var(--font-mono);
}

* {
    color: var(--text-3000) !important;
    border-color: var(--border-bold) !important;
    text-shadow: var(--terminal-glow);
    font-family: var(--font-mono) !important;
}

.TopBar3000__content {
    border-bottom: solid 1px var(--border-bold);
}

button,
input[type="button"],
input[type="submit"],
a,
[class*="btn"],
[class*="Button"],
[class*="button-primitive"],
[class*="LemonButton"],
[class*="ant-btn"],
[class*="group/button-primitive"] {
    background-color: var(--bg-3000) !important;
    color: var(--text-3000) !important;
    border: 1px solid var(--border-bold) !important;
    border-radius: var(--radius) !important;
    font-weight: bold !important;
    text-transform: uppercase;
    cursor: pointer !important;
    box-shadow: var(--terminal-glow) !important;
    transition: all 0.2s ease;
}

/* Override any warning/highlight button states */
[class*="warning"],
[class*="Warning"],
[class*="highlight"],
[class*="Highlight"],
[class*="yellow"],
[class*="Yellow"] {
    background-color: var(--bg-3000) !important;
    color: var(--text-3000) !important;
    border-color: var(--border-bold) !important;
}

button:hover,
input[type="button"]:hover,
input[type="submit"]:hover,
a:hover,
[class*="btn"]:hover,
[class*="Button"]:hover,
[class*="button-primitive"]:hover,
[class*="LemonButton"]:hover,
[class*="ant-btn"]:hover,
[class*="group/button-primitive"]:hover {
    background-color: var(--primary-3000) !important;
    color: var(--bg-3000) !important;
    border-color: var(--primary-3000) !important;
    box-shadow: 0 0 15px var(--primary-3000) !important;
}

.LemonButton__content,
[class*="__content"],
[class*="__label"],
[class*="__icon"],
button span,
button div,
a span,
a div {
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
} 

button svg,
a svg,
[class*="btn"] svg,
[class*="Button"] svg,
[class*="button-primitive"] svg,
[class*="LemonButton"] svg,
[class*="ant-btn"] svg {
    color: inherit !important;
    fill: currentColor !important;
    filter: drop-shadow(var(--terminal-glow));
    width: 16px;
    height: 16px;
}

a:not([class*="button"]):not([class*="btn"]) {
    color: var(--link);
    border-bottom: 1px solid transparent;
    transition: all 0.2s ease;
}

a:not([class*="button"]):not([class*="btn"]):hover {
    background-color: var(--primary-3000);
    color: var(--bg-3000);
    border-bottom-color: transparent;
    box-shadow: var(--terminal-glow);
}`

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
        <div className="flex flex-col deprecated-space-y-2">
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
                our templates: <Link onClick={() => setPreviewingCustomCss(TRON_THEME)}>Tron</Link>,{' '}
                <Link onClick={() => setPreviewingCustomCss(BARBIE_THEME)}>Barbie</Link>,{' '}
                <Link onClick={() => setPreviewingCustomCss(LUMON_THEME)}>Lumon</Link>
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
