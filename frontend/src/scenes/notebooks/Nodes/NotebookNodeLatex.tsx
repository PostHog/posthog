import { mergeAttributes } from '@tiptap/core'
import { InputRule } from '@tiptap/core'
import { browserAdaptor } from 'mathjax-full/js/adaptors/browserAdaptor.js'
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js'
import { TeX } from 'mathjax-full/js/input/tex.js'
// MathJax local import and config
import { mathjax } from 'mathjax-full/js/mathjax.js'
import { SVG } from 'mathjax-full/js/output/svg.js'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { NotebookNodeProps, CustomNotebookNodeAttributes } from '../Notebook/utils'
import { useEffect, useRef } from 'react'

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

const LatexComponent = ({ attributes }: NotebookNodeProps<NotebookNodeLatexAttributes>): JSX.Element => {
    const content = attributes.content
    const containerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (containerRef.current) {
            const element = containerRef.current
            if (content) {
                try {
                    // Clear previous content
                    element.innerHTML = ''
                    // Render with MathJax
                    const math = mjxDocument.convert(content, { display: true })
                    element.appendChild(math)
                } catch (err) {
                    element.innerHTML = '<span style="color:red">LaTeX error</span>'
                    console.error('MathJax error:', err)
                }
            } else {
                element.innerHTML = '' // Clear if no content
            }
        }
    }, [content])

    return <div ref={containerRef} className="NotebookLatex text-center" data-latex-block />
}

const DEFAULT_ATTRIBUTES_WITH_DEFAULTS = {
    content: { default: '' },
    editing: { default: false },
}

export const NotebookNodeLatex = createPostHogWidgetNode<NotebookNodeLatexAttributes>({
    nodeType: NotebookNodeType.Latex,
    titlePlaceholder: 'LaTeX',
    Component: LatexComponent,
    heightEstimate: '4rem',
    minHeight: '2rem',
    resizeable: false,
    attributes: DEFAULT_ATTRIBUTES_WITH_DEFAULTS,
    serializedText: (attrs) => attrs.content,
}).extend({
    parseHTML() {
        return [
            {
                tag: 'div[data-latex-block]',
                getAttrs: (dom: HTMLElement | string) => {
                    const element = dom as HTMLElement
                    return { content: element.textContent || '' }
                },
            },
        ]
    },
    renderHTML({ HTMLAttributes, node }) {
        const content = node.attrs.content
        return [
            'div',
            mergeAttributes(HTMLAttributes, {
                class: 'NotebookLatex',
                'data-latex-block': true,
                style: 'text-align: center;',
            }),
            content, // Store raw LaTeX content for MathJax processing in the component
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
                        .insertContent({ type: NotebookNodeLatex.name, attrs: { content: latex } })
                        .run()
                },
            }),
        ]
    },
})
