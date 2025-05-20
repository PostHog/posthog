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

const DOS_THEME = `/* === DOS-style font & pixel render === */
@import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');

:root {
  --dos-bg:        #000030;
  --dos-fg:        #FFFFFF;
  --dos-blue:      #0000AA;
  --dos-cyan:      #00FFFF;
  --dos-gray:      #888888;
}
* {
  border-radius: 0 !important;
  box-shadow:    none !important;
}

/* === Global body === */
body {
  background:        var(--dos-bg)   !important;
  color:             var(--dos-fg)   !important;
  font-family:       'VT323', monospace !important;
  font-size:         14px            !important;
  -webkit-font-smoothing: none       !important;
  image-rendering:   pixelated       !important;
  margin:            0;
  padding:           0;
  overflow:          hidden;
}
/* === Full-screen container === */
#root, .App, .LemonLayout {
  background: var(--dos-blue) !important;
  border:     2px solid var(--dos-fg) !important;
  padding:    0 !important;
  margin:     0;
}

/* === Top bar / menu bar === */
.TopBar3000__content,
.LemonTabs {
  background:        var(--dos-cyan) !important;
  color:             var(--dos-bg)  !important;
  border-bottom:     2px solid var(--dos-fg) !important;
  padding:           4px 8px         !important;
  text-transform:    uppercase;
  font-weight:       bold;
}

/* === Sidebar === */
.Sidebar, .Menu {
  background:    var(--dos-blue) !important;
  color:         var(--dos-fg)  !important;
  border-right:  2px solid var(--dos-fg) !important;
}
.Sidebar a,
.Menu a {
  display:       block;
  padding:       2px 6px       !important;
  color:         var(--dos-cyan) !important;
  text-decoration:none;
}
.Sidebar a:hover, .Menu a.active {
  background:    var(--dos-cyan) !important;
  color:         var(--dos-bg)  !important;
}

/* === Panels, cards, modals === */
.LemonCard,
.LemonModal,
.LemonPopover,
.LemonTable,
.Panel {
  background: var(--dos-bg) !important;
  color:      var(--dos-fg) !important;
  border:     2px solid var(--dos-fg) !important;
}

/* === Buttons & links === */
button,
.LemonButton,
.Link {
  background:      var(--dos-blue)   !important;
  color:           var(--dos-fg)    !important;
  border:          2px solid var(--dos-fg) !important;
  padding:         2px 6px !important;
  text-transform:  uppercase !important;
  font-family:     'VT323', monospace !important;
  font-size:       13px !important;
}
button:hover,
.LemonButton:hover,
.Link:hover {
  background: var(--dos-cyan) !important;
  color:      var(--dos-bg)  !important;
}

/* === Inputs & selects === */
input, textarea, select {
  background: var(--dos-bg) !important;
  color:      var(--dos-fg) !important;
  border:     1px solid var(--dos-fg) !important;
}

/* === Block selection highlight === */
::selection {
  background: var(--dos-cyan) !important;
  color:      var(--dos-bg)  !important;
}

/* === Scanlines overlay === */
body::before {
  content:   "";
  position:  fixed;
  top:0; left:0; right:0; bottom:0;
  background: linear-gradient(rgba(255,255,255,0.03) 50%, transparent 50%);
  background-size: 100% 2px;
  pointer-events: none;
  z-index: 9998;
}

/* === Footer hints (ESC, ↑↓, ENTER) === */
body::after {
  content:    "ESC: Exit    ↑/↓: Move    ENTER: Select";
  position:   fixed;
  bottom:     0; left: 0; right: 0;
  background: var(--dos-blue) !important;
  color:      var(--dos-fg)  !important;
  border-top: 2px solid var(--dos-fg) !important;
  padding:    2px 8px !important;
  font-family:'VT323',monospace !important;
  font-size:  12px !important;
  z-index:    9999;
}

/* === Blinking cursor helper === */
@keyframes dos-blink {
  0%,100% { opacity:1; }
  50%    { opacity:0; }
}
.blinking-cursor::after {
  content: "_";
  animation: dos-blink 1s step-end infinite;
  color: var(--dos-fg);
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
                <Link onClick={() => setPreviewingCustomCss(DOS_THEME)}>DOS</Link>
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
