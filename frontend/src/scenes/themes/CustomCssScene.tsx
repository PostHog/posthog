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

    --lumon-blue: #93C4FF;
    --lumon-bg: #000000;
    --glow: 0 0 10px rgba(147, 196, 255, 0.25);
    --bloom: 0 0 25px rgba(147, 196, 255, 0.5);
}

/* === Base Body Styling === */
body,
body[theme='dark'] {
    background: var(--lumon-bg);
    color: var(--lumon-blue);
    font-family: var(--font-mono);
    text-shadow: var(--glow);
    position: relative;
    overflow: hidden;
    filter: contrast(1.8) brightness(1.4) saturate(1.3);
    animation: flicker 0.2s infinite;
}

@keyframes flicker {
    0%, 100% { opacity: 0.98; }
    50% { opacity: 1; }
    25%, 75% { opacity: 0.96; }
}

/* === CRT Rounded Tube Shadow === */
body::before {
    content: '';
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 9996;
    background-image: url('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQMAAAAl21bKAAAABlBMVEUAAAD///+l2Z/dAAAACklEQVQI12NgAAAAAgAB4iG8MwAAAABJRU5ErkJggg==');
    background-size: 1px 1px;
    opacity: 0.4;
    image-rendering: pixelated;
    mix-blend-mode: overlay;
}

body::before.overlay {
    content: '';
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 9998;
    border-radius: 5% / 3%;
    background:
        radial-gradient(circle at center, rgba(147, 196, 255, 0.04), transparent 70%) no-repeat center,
        linear-gradient(to right, rgba(255,255,255,0.04) 0%, transparent 20%, transparent 80%, rgba(255,255,255,0.04) 100%);
    box-shadow:
        inset 0 0 300px rgba(0, 0, 0, 0.75),
        inset 0 0 800px rgba(0, 0, 0, 0.6);
    mix-blend-mode: overlay;
}

/* === Scanlines Overlay === */
body::after {
    content: '';
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 9999;
    background: repeating-linear-gradient(
        to bottom,
        rgba(255, 255, 255, 0.03) 0px,
        rgba(255, 255, 255, 0.03) 2px,
        transparent 2px,
        transparent 4px
    );
    mix-blend-mode: overlay;
    animation: scanline-glide 0.75s linear infinite;
    opacity: 0.25;
}

@keyframes scanline-glide {
    0% { background-position: 0 0; }
    100% { background-position: 0 100%; }
}

/* === Pixelation Overlay (separate layer) === */
html::before {
    content: '';
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 9997;
    background-image: url('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQMAAAAl21bKAAAABlBMVEUAAAD///+l2Z/dAAAACklEQVQI12NgAAAAAgAB4iG8MwAAAABJRU5ErkJggg==');
    background-size: 1px 1px;
    opacity: 0.3;
    image-rendering: pixelated;
    mix-blend-mode: overlay;
}

/* === Global Font + Color Rules === */
* {
    font-family: var(--font-mono) !important;
    color: var(--lumon-blue) !important;
    border-color: var(--lumon-blue) !important;
    text-shadow:
        var(--glow),
        -0.25px 0 rgba(255, 0, 0, 0.3),
        0.25px 0 rgba(0, 0, 255, 0.3);
}

/* === Button Styling === */
button,
input[type="button"],
input[type="submit"],
a,
[class*="btn"],
[class*="Button"],
[class*="button-primitive"],
[class*="LemonButton"],
[class*="ant-btn"],
[class*="group/button-primitive"],
.LemonButton > span::after {
    background: var(--lumon-bg) !important;
    color: var(--lumon-blue) !important;
    border: 1px solid var(--lumon-blue) !important;
    border-radius: var(--radius);
    font-weight: bold;
    text-transform: uppercase;
    cursor: pointer;
    box-shadow: var(--glow);
    transition: all 0.2s ease;
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
    background: var(--lumon-blue) !important;
    color: var(--lumon-bg) !important;
    border-color: var(--lumon-blue) !important;
    box-shadow: var(--bloom) !important;
}

button:hover *,
a:hover *,
[class*="btn"]:hover *,
[class*="Button"]:hover *,
[class*="button-primitive"]:hover *,
[class*="LemonButton"]:hover *,
[class*="ant-btn"]:hover * {
    color: var(--lumon-bg) !important;
    fill: var(--lumon-bg) !important;
}

[class*="warning"],
[class*="highlight"],
[class*="yellow"] {
    background: var(--lumon-bg) !important;
    color: var(--lumon-blue) !important;
    border-color: var(--lumon-blue) !important;
}

[class*="__content"],
[class*="__label"],
[class*="__icon"],
button span,
button div,
a span,
a div,
.LemonButton > span::after {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: inherit !important;
}

button svg,
a svg,
[class*="btn"] svg,
[class*="Button"] svg,
[class*="button-primitive"] svg,
[class*="LemonButton"] svg,
[class*="ant-btn"] svg {
    fill: currentColor !important;
    color: inherit !important;
    filter: drop-shadow(var(--glow));
    width: 16px;
    height: 16px;
}

a:not([class*="button"]):not([class*="btn"]) {
    color: var(--lumon-blue);
    border-bottom: 1px solid transparent;
    transition: 0.2s ease;
}

a:not([class*="button"]):not([class*="btn"]):hover {
    background: var(--lumon-blue);
    color: var(--lumon-bg);
    box-shadow: var(--glow);
    border-bottom: none;
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
