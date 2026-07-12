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

export interface MermaidDiagramProps {
    code: string
    className?: string
}

export function MermaidDiagram({ code, className }: MermaidDiagramProps): JSX.Element {
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
                    mermaid.initialize({
                        startOnLoad: false,
                        theme: isDarkModeOn ? 'dark' : 'default',
                        securityLevel: 'strict',
                        fontFamily: 'inherit',
                    })
                    initializedTheme = isDarkModeOn
                }
                return mermaid.render(diagramId, code)
            })
            .then((result) => {
                if (cancelled || !result) {
                    return
                }
                setSvg(result.svg)
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
    }, [code, isDarkModeOn, diagramId])

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
