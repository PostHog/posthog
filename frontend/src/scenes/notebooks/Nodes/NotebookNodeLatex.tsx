import { browserAdaptor } from '@mathjax/src/mjs/adaptors/browserAdaptor.js'
import { RegisterHTMLHandler } from '@mathjax/src/mjs/handlers/html.js'
import { TeX } from '@mathjax/src/mjs/input/tex.js'
import { mathjax } from '@mathjax/src/mjs/mathjax.js'
import { SVG } from '@mathjax/src/mjs/output/svg.js'
import { useEffect, useRef, useState } from 'react'

import { LemonTextArea } from '@posthog/lemon-ui'

import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { CustomNotebookNodeAttributes, NotebookNodeProps, NotebookNodeType } from '../types'

RegisterHTMLHandler(browserAdaptor())
const tex = new TeX({
    packages: ['base', 'ams'],
    inlineMath: [['$', '$']],
    displayMath: [['$$', '$$']],
    processEscapes: true,
    processEnvironments: true,
})
const svg = new SVG({ fontCache: 'none' })
const mjxDocument = mathjax.document(document, { InputJax: tex, OutputJax: svg })

// Renders LaTeX to an SVG node. MathJax v4's modern SVG font loads glyph data lazily from "dynamic
// files" (e.g. 'shapes', 'arrows'); convert() defers those loads through the retry mechanism, so we
// run it inside handleRetriesFor() to await them. The returned promise rejects if a dynamic file
// fails to load, which is async and a synchronous try/catch would miss, so callers must catch it.
export function renderLatexToNode(content: string): Promise<Node> {
    return mathjax.handleRetriesFor(() => mjxDocument.convert(content, { display: true }))
}

interface NotebookNodeLatexAttributes extends CustomNotebookNodeAttributes {
    content: string
    editing: boolean
}

const LatexComponent = ({
    attributes,
    updateAttributes,
    selected,
}: NotebookNodeProps<NotebookNodeLatexAttributes> & { selected?: boolean }): JSX.Element => {
    const { content, editing } = attributes
    const [localContent, setLocalContent] = useState(content)
    const containerRef = useRef<HTMLDivElement>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)

    useEffect(() => {
        setLocalContent(content)
    }, [content])

    useEffect(() => {
        if (editing && textareaRef.current) {
            textareaRef.current.focus()
            textareaRef.current.style.height = 'auto'
            textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`
        }
    }, [editing])

    useEffect(() => {
        const mathJaxDisplayDiv = containerRef.current // The div for displaying rendered MathJax

        if (!mathJaxDisplayDiv) {
            return
        }

        if (editing || !content) {
            mathJaxDisplayDiv.innerHTML = ''
            return
        }

        // A failed dynamic font load rejects asynchronously, so we catch it and fall back to a
        // friendly message rather than letting it surface as an unhandled error. See renderLatexToNode.
        let cancelled = false
        mathJaxDisplayDiv.innerHTML = '' // Clear before rendering
        renderLatexToNode(content)
            .then((math: Node) => {
                if (!cancelled) {
                    mathJaxDisplayDiv.innerHTML = ''
                    mathJaxDisplayDiv.appendChild(math)
                }
            })
            .catch((err: unknown) => {
                if (!cancelled) {
                    mathJaxDisplayDiv.innerHTML = '<span style="color:red">LaTeX error</span>'
                }
                console.error('MathJax error:', err)
            })

        return () => {
            cancelled = true
        }
    }, [content, editing])

    const handleSave = (): void => {
        updateAttributes({ content: localContent, editing: false })
    }

    const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>): void => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            handleSave()
        }
    }

    return (
        <>
            {/* Display mode: Render the div that MathJax will populate, hidden when editing */}
            <div
                ref={containerRef} // This ref is for the display div
                className={`NotebookLatex text-center cursor-pointer hover:bg-border p-1 rounded ${
                    selected ? 'NotebookNode--selected' : ''
                } ${editing ? 'hidden' : ''}`}
                data-latex-block
                onClick={() => {
                    // This div is hidden when editing is true, so this click handler
                    // will only be active when not editing.
                    if (!editing) {
                        updateAttributes({ editing: true })
                    }
                }}
                title={editing ? undefined : 'Click to edit LaTeX'}
            />

            {editing && (
                <div className="p-2 w-full" data-nodrag="true">
                    <LemonTextArea
                        ref={textareaRef}
                        value={localContent}
                        onChange={(value: string) => setLocalContent(value)}
                        onBlur={handleSave}
                        onKeyDown={handleKeyDown}
                        className="w-full text-sm"
                        placeholder="Enter LaTeX, e.g. E = mc^2"
                        minRows={1}
                    />
                </div>
            )}
        </>
    )
}

const DEFAULT_ATTRIBUTES_WITH_DEFAULTS = {
    content: { default: '' },
    editing: { default: true }, // Start in editing mode when newly inserted
}

export const NotebookNodeLatex = createPostHogWidgetNode<NotebookNodeLatexAttributes>({
    nodeType: NotebookNodeType.Latex,
    titlePlaceholder: 'LaTeX',
    Component: LatexComponent,
    heightEstimate: 'auto', // Adjust height estimate as input can grow
    minHeight: '3rem',
    resizeable: true, // Allow resizing if content is large when not editing
    attributes: DEFAULT_ATTRIBUTES_WITH_DEFAULTS,
    serializedText: (attrs) => attrs.content,
    inputOptions: {
        find: /(?:^|\s)\$\$([^$\n]+?)\$\$(?=\s|$)/,
        getAttributes: (match) => {
            const latex = match[1].trim()
            return { content: latex, editing: false }
        },
    },
})
