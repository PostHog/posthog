import { Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { LemonMarkdown, LemonMarkdownProps } from './LemonMarkdown'

const LazyMermaidDiagram = lazyWithRetry(() => import('./MermaidDiagram'))

function renderMermaid(code: string): JSX.Element {
    return (
        <Suspense fallback={<Spinner />}>
            <LazyMermaidDiagram code={code} />
        </Suspense>
    )
}

/**
 * `LemonMarkdown` with Mermaid diagram rendering enabled. Use this in surfaces that need to render
 * ` ```mermaid ` fences (skills, prompts) — the mermaid library is loaded into its own chunk on
 * demand, so only bundles that opt in pay the cost.
 */
export function LemonMarkdownWithMermaid(props: Omit<LemonMarkdownProps, 'renderMermaid'>): JSX.Element {
    return <LemonMarkdown {...props} renderMermaid={renderMermaid} />
}
