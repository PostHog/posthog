import { Suspense, lazy } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { NotebookCodeBlockNode } from './types'

// Loaded on demand so the mermaid library ships in its own chunk rather than the notebook bundle.
const LazyMermaidDiagram = lazy(() => import('lib/lemon-ui/LemonMarkdown/MermaidDiagram'))

export function isMermaidCodeBlock(node: NotebookCodeBlockNode): boolean {
    return node.language?.toLowerCase() === 'mermaid'
}

export function NotebookMermaidBlock({
    node,
    setBlockRef,
}: {
    node: NotebookCodeBlockNode
    setBlockRef: (element: HTMLElement | null) => void
}): JSX.Element {
    return (
        <div
            className="MarkdownNotebook__mermaid-block"
            ref={setBlockRef}
            contentEditable={false}
            data-markdown-notebook-node-id={node.id}
        >
            <Suspense
                fallback={
                    <div className="flex items-center justify-center p-4">
                        <Spinner />
                    </div>
                }
            >
                <LazyMermaidDiagram code={node.text} naturalWidth />
            </Suspense>
        </div>
    )
}
