import { useValues } from 'kea'
import { useEffect, useId, useState } from 'react'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { themeLogic } from 'lib/logic/themeLogic'

type MermaidApi = {
    initialize: (config: Record<string, unknown>) => void
    render: (id: string, code: string) => Promise<{ svg: string }>
}

let mermaidPromise: Promise<MermaidApi> | null = null

function loadMermaid(): Promise<MermaidApi> {
    if (!mermaidPromise) {
        mermaidPromise = import('mermaid').then((module) => module.default as MermaidApi)
    }
    return mermaidPromise
}

// Module-scoped so mermaid.initialize runs at most once per theme change across the whole page,
// not once per <MermaidDiagram> instance.
let initializedTheme: boolean | null = null
let diagramCounter = 0

// PostHog data-viz palette (frontend/src/styles/base.scss `--data-color-*`). Read live from the
// CSS variables so charts stay in sync with the theme; the hex fallbacks match base.scss in case
// the variables can't be resolved (e.g. a detached render).
const DATA_COLOR_FALLBACKS = [
    '#1d4aff',
    '#621da6',
    '#42827e',
    '#ce0e74',
    '#f14f58',
    '#7c440e',
    '#529a0a',
    '#0476fb',
    '#fe729e',
    '#35416b',
    '#41cbc4',
    '#b64b02',
]

function cssVar(name: string, fallback: string): string {
    if (typeof document === 'undefined') {
        return fallback
    }
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

// Build a PostHog-suited mermaid config: the brand data palette for series, theme-aware text, and
// a transparent background so diagrams sit cleanly on whatever surface renders them.
function buildMermaidConfig(isDarkModeOn: boolean): Record<string, unknown> {
    const palette = DATA_COLOR_FALLBACKS.map((fallback, i) => cssVar(`--data-color-${i + 1}`, fallback))
    const text = cssVar('--text-3000', isDarkModeOn ? '#ffffff' : '#111827')
    // --border-bold is a single translucent black, so it disappears on dark surfaces; the
    // -3000 variable is the theme-switched one.
    const line = cssVar('--border-bold-3000', isDarkModeOn ? '#3f4046' : '#c1c2b9')

    const seriesVars = palette.reduce<Record<string, string>>((acc, color, i) => {
        acc[`pie${i + 1}`] = color
        acc[`cScale${i}`] = color
        return acc
    }, {})

    return {
        startOnLoad: false,
        theme: 'base',
        securityLevel: 'strict',
        fontFamily: 'inherit',
        themeVariables: {
            darkMode: isDarkModeOn,
            background: 'transparent',
            primaryColor: palette[0],
            primaryBorderColor: palette[1],
            // Node labels sit on a saturated palette fill in both themes, so they follow the fill
            // rather than the page. `textColor` still themes the labels drawn on the background.
            primaryTextColor: '#ffffff',
            secondaryColor: palette[1],
            tertiaryColor: palette[2],
            lineColor: line,
            textColor: text,
            ...seriesVars,
            // xychart-beta reads none of the variables above: its palette, its plot background and
            // every axis color live under `xyChart`. Left alone it paints a pale-cream plot
            // (#FFF4DD) on an opaque white card, which reads as a hole in a dark page.
            xyChart: {
                plotColorPalette: palette.join(', '),
                backgroundColor: 'transparent',
                titleColor: text,
                xAxisLabelColor: text,
                xAxisTitleColor: text,
                xAxisTickColor: line,
                xAxisLineColor: line,
                yAxisLabelColor: text,
                yAxisTitleColor: text,
                yAxisTickColor: line,
                yAxisLineColor: line,
            },
        },
    }
}

export interface MermaidDiagramProps {
    code: string
    className?: string
    /** Render at the diagram's intrinsic width instead of shrinking to fit the container.
     * Use inside a horizontally scrollable wrapper so wide diagrams scroll rather than becoming unreadably small. */
    naturalWidth?: boolean
}

// Mermaid sizes its SVG with width="100%" plus an inline max-width of the intrinsic size, which
// scales wide diagrams down to the container. Inline styles beat any stylesheet rule, so the only
// way to let a scroll container take over is to rewrite the inline sizing to a fixed width.
function withNaturalWidth(svgMarkup: string): string {
    const host = document.createElement('div')
    host.innerHTML = svgMarkup
    const svgElement = host.querySelector('svg')
    if (svgElement && svgElement.style.maxWidth) {
        svgElement.style.width = svgElement.style.maxWidth
        svgElement.style.maxWidth = ''
    }
    return host.innerHTML
}

export function MermaidDiagram({ code, className, naturalWidth = false }: MermaidDiagramProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const reactId = useId()
    const [diagramId] = useState(() => {
        diagramCounter += 1
        const safe = reactId.replace(/[^a-zA-Z0-9_-]/g, '')
        return `mermaid-${safe}-${diagramCounter}`
    })

    const [svg, setSvg] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        let cancelled = false
        setLoading(true)
        setError(null)

        loadMermaid()
            .then((mermaid) => {
                if (cancelled) {
                    return null
                }
                if (initializedTheme !== isDarkModeOn) {
                    mermaid.initialize(buildMermaidConfig(isDarkModeOn))
                    initializedTheme = isDarkModeOn
                }
                return mermaid.render(diagramId, code)
            })
            .then((result) => {
                if (cancelled || !result) {
                    return
                }
                setSvg(naturalWidth ? withNaturalWidth(result.svg) : result.svg)
            })
            .catch((err: unknown) => {
                if (cancelled) {
                    return
                }
                setError(err instanceof Error ? err.message : 'Unable to render diagram')
            })
            .finally(() => {
                if (!cancelled) {
                    setLoading(false)
                }
            })

        return () => {
            cancelled = true
        }
    }, [code, isDarkModeOn, diagramId, naturalWidth])

    if (error) {
        return (
            <div className={className} data-attr="mermaid-error">
                <div className="mb-1 text-xs text-danger">Could not render Mermaid diagram: {error}</div>
                <CodeSnippet language={Language.Text} compact wrap>
                    {code}
                </CodeSnippet>
            </div>
        )
    }

    if (loading && !svg) {
        return (
            <div className={`flex items-center justify-center p-4 ${className ?? ''}`} data-attr="mermaid-loading">
                <Spinner />
            </div>
        )
    }

    return (
        <div
            className={`LemonMarkdown__mermaid ${className ?? ''}`}
            data-attr="mermaid-rendered"
            // eslint-disable-next-line react/no-danger -- mermaid sanitizes output via securityLevel: 'strict'
            dangerouslySetInnerHTML={svg ? { __html: svg } : undefined}
        />
    )
}

export default MermaidDiagram
