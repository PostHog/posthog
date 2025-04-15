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

const LUMON_THEME = `
/* === Import Input Sans Font from Google Fonts === */
@import url('https://fonts.googleapis.com/css2?family=Input+Sans:wght@300;400;500;600&display=swap');

/* === Override default variables === */
:root {
    --color-background: #000920; /* Deep dark blue background */
    --color-primary: #00e5ff;   /* Brighter cyan-blue color */
    --color-accent: #9fefff;    /* Lighter accent color */
    --font-mono: "Courier New", monospace;
    --font-main: "Input Sans", sans-serif; /* Use Input Sans for the font */
}

/* === Base body and layout styles === */
body {
    font-family: var(--font-main) !important; /* Apply Input Sans to the body */
    background-color: var(--color-background) !important;
    color: var(--color-primary) !important;
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    height: 100%;
    margin: 0;
    overflow: hidden;
    text-shadow: 0 0 10px var(--color-primary), 0 0 20px var(--color-primary); /* Glowing text */
    animation: flicker 8s infinite, distort 6s infinite; /* Slowed down flicker and distortion */
}

/* === CRT screen effects === */
body:before {
    content: "";
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-color: #0a192f;
    box-shadow: inset 0 0 150px rgba(0, 60, 120, 0.5), inset 0 0 50px rgba(0, 30, 60, 0.5); /* Vignette effect */
    z-index: -999;
}

/* Scanlines effect */
body::after {
    content: "";
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: linear-gradient(to bottom, rgba(0, 229, 255, 0.1) 50%, rgba(0, 0, 0, 0.5) 50%);
    background-size: 100% 2px;
    z-index: 9999;
    pointer-events: none;
    opacity: 0.72; /* Dialed back opacity for slightly less noticeable lines */
}

/* === Fill colors for the graph's areas === */
.LineGraph .graph-area {
    fill: rgba(0, 229, 255, 0.15) !important;  /* Light cyan-blue fill */
}

/* === Graph lines === */
.LineGraph .graph-line {
    stroke: var(--color-primary) !important; /* Cyan-blue for graph lines */
}

/* === Axis lines === */
.LineGraph .graph-axis {
    stroke: rgba(0, 229, 255, 0.6) !important;  /* Brighter cyan-blue for axis lines */
}

/* === Grid lines === */
.LineGraph .graph-grid {
    stroke: rgba(0, 229, 255, 0.1) !important;  /* Faint cyan-blue grid lines */
}

/* === Annotations and Badges === */
.AnnotationsBadge {
    background-color: rgba(13, 42, 73, 0.8) !important; /* Dark cyan-blue background for badges */
    color: var(--color-primary) !important;  /* Cyan-blue text */
    border: 1px solid rgba(0, 229, 255, 0.3) !important;  /* Accent cyan-blue borders */
    box-shadow: 0 0 10px rgba(0, 229, 255, 0.2) !important;  /* Subtle glowing effect */
    transition: all 0.3s ease !important;  /* Smooth transition for hover effects */
}

/* Hover effects for Annotation Badges */
.AnnotationsBadge:hover {
    background-color: rgba(20, 66, 114, 0.9) !important;  /* Lighter hover background */
    border-color: var(--color-primary) !important;
    box-shadow: 0 0 20px rgba(0, 229, 255, 0.4) !important;  /* Brighter glow on hover */
    color: #000920 !important;  /* Change text to black for contrast on hover */
}

/* === Button Style for Graph Annotations === */
.LemonBadge {
    background-color: rgba(13, 42, 73, 0.8) !important;  /* Matching badge background */
    border: 1px solid rgba(0, 229, 255, 0.3) !important;
}

/* === Apply uppercase and color transformation to the LemonButton content === */
.LemonButton__content {
    text-transform: uppercase !important; /* Ensure all button text is in uppercase */
    color: var(--color-primary) !important;  /* Set the text color to cyan-blue */
}

/* === Apply uppercase and color transformation for LemonButton span === */
.LemonButton__chrome {
    color: var(--color-primary) !important;  /* Make sure the span color is also set to cyan-blue */
}

/* === Make Text on Buttons All Caps using ::after for LemonButton */
.LemonButton > span::after {
    content: attr(data-text); /* Ensures the content is respected */
    text-transform: uppercase !important; /* Make text all caps */
    display: inline-block; /* Ensure the text behaves as a block-level element */
}

/* === Uppercase Text and Color for button-primitive class === */
.button-primitive .truncate {
    text-transform: uppercase !important; /* Make text uppercase */
    color: var(--color-primary) !important;  /* Ensure text color is cyan-blue */
}

/* === Uppercase Text and Color for button-primitive content === */
.button-primitive > a .truncate {
    text-transform: uppercase !important; /* Make text uppercase */
    color: var(--color-primary) !important;  /* Ensure text color is cyan-blue */
}

/* === Tooltip or Badge Hover Text === */
.AnnotationsBadge span {
    font-size: 0.9rem;
    color: var(--color-primary) !important;
}

/* === SVG Icons in Badges === */
.LemonIcon {
    fill: var(--color-primary) !important; /* Make icons cyan-blue */
    transition: fill 0.3s ease;
}

/* === Graph Legends and Tooltips === */
.InsightVizDisplay__content .Tooltip {
    background-color: rgba(0, 29, 58, 0.8) !important;  /* Dark cyan background for tooltips */
    color: var(--color-primary) !important;  /* Cyan-blue text */
    border: 1px solid rgba(0, 229, 255, 0.3) !important;  /* Accent cyan-blue borders */
}

/* === Graph Ticks and Labels === */
.LineGraph .graph-tick {
    fill: var(--color-primary) !important; /* Cyan-blue tick marks */
}

/* === Blinking cursor effect for badges (if necessary) */
@keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
}

.Header_Header__GCJdR h1::after {
    content: "_";
    animation: blink 1s infinite;
    color: var(--color-primary);
    font-weight: normal;
}

/* === Flicker animation - Slowed down */
@keyframes flicker {
    0% { opacity: 1.0; }
    10% { opacity: 0.9; }
    20% { opacity: 1.0; }
    30% { opacity: 1.0; }
    40% { opacity: 0.95; }
    50% { opacity: 1.0; }
    60% { opacity: 1.0; }
    70% { opacity: 0.97; }
    80% { opacity: 1.0; }
    100% { opacity: 1.0; }
}

/* Subtle horizontal distortion like an old CRT */
@keyframes distort {
    0% { transform: translateX(0); }
    5% { transform: translateX(-0.5px); }
    10% { transform: translateX(0.5px); }
    15% { transform: translateX(0); }
    100% { transform: translateX(0); }
}

/* === Link Button Style === */
.Link {
    background-color: rgba(13, 42, 73, 0.8) !important;  /* Matching background */
    border: 1px solid rgba(0, 229, 255, 0.3) !important;  /* Cyan-blue borders */
    color: var(--color-primary) !important;  /* Cyan-blue text */
    text-transform: uppercase !important;  /* Ensure text is in uppercase */
    padding: 10px 20px; /* Adjust padding for a better look */
    font-family: var(--font-main) !important; /* Apply Input Sans font */
    font-weight: 600;  /* Make text bold */
    transition: all 0.3s ease !important;  /* Smooth transition */
    cursor: pointer;
}

/* === Hover Effects for Link Button === */
.Link:hover {
    background-color: rgba(20, 66, 114, 0.9) !important;  /* Lighter hover background */
    border-color: var(--color-primary) !important;
    box-shadow: 0 0 20px rgba(0, 229, 255, 0.4) !important;  /* Glowing effect */
    color: #000920 !important;  /* Change text to black for contrast */
}

/* === Focus Effect for Link Button === */
.Link:focus {
    outline: none;  /* Remove default focus outline */
    box-shadow: 0 0 10px rgba(0, 229, 255, 0.6) !important;  /* Glowing border on focus */
}

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
