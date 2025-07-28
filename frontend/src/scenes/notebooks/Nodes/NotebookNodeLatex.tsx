import { mergeAttributes } from '@tiptap/core'
import { InputRule } from '@tiptap/core'
import { browserAdaptor } from 'mathjax-full/js/adaptors/browserAdaptor.js'
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js'
import { TeX } from 'mathjax-full/js/input/tex.js'
import { mathjax } from 'mathjax-full/js/mathjax.js'
import { SVG } from 'mathjax-full/js/output/svg.js'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { useEffect, useRef, useState } from 'react'
import { LemonTextArea } from '@posthog/lemon-ui'
import { NotebookNodeProps, NotebookNodeType, CustomNotebookNodeAttributes } from '../types'

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

        if (mathJaxDisplayDiv) {
            if (!editing && content) {
                try {
                    mathJaxDisplayDiv.innerHTML = '' // Clear before rendering
                    const math = mjxDocument.convert(content, { display: true })
                    mathJaxDisplayDiv.appendChild(math)
                } catch (err) {
                    mathJaxDisplayDiv.innerHTML = '<span style="color:red">LaTeX error</span>'
                    console.error('MathJax error:', err)
                }
            } else {
                mathJaxDisplayDiv.innerHTML = ''
            }
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
}).extend({
    selectable: true,
    parseHTML() {
        return [
            {
                tag: 'div[data-latex-block]',
                getAttrs: (dom: HTMLElement | string) => {
                    const element = dom as HTMLElement
                    return { content: element.textContent || '', editing: false }
                },
            },
        ]
    },
    renderHTML({ HTMLAttributes }) {
        return [
            'div',
            mergeAttributes(HTMLAttributes, {
                class: 'NotebookLatex',
                'data-latex-block': true,
                style: 'text-align: center;',
            }),
            // Do not render content string here; LatexComponent handles all rendering!!!1
        ]
    },
    addInputRules() {
        return [
            new InputRule({
                find: /(?:^|\s)\$\$([^$\n]+?)\$\$(?=\s|$)/,
                handler: ({ match, chain, range }) => {
                    if (match.index === undefined) {
                        return
                    }
                    const latex = match[1].trim()
                    const start = range.from + (match[0].startsWith(' ') ? 1 : 0)
                    const end = range.to - (match[0].endsWith(' ') ? 1 : 0)

                    chain()
                        .deleteRange({ from: start, to: end })
                        .insertContent({ type: NotebookNodeLatex.name, attrs: { content: latex, editing: false } })
                        .run()
                },
            }),
        ]
    },
})
