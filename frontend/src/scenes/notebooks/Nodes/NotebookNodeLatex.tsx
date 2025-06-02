import { mergeAttributes, Node } from '@tiptap/core'
import { InputRule } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { EditorView } from '@tiptap/pm/view'
import { browserAdaptor } from 'mathjax-full/js/adaptors/browserAdaptor.js'
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js'
import { TeX } from 'mathjax-full/js/input/tex.js'
// MathJax local import and config
import { mathjax } from 'mathjax-full/js/mathjax.js'
import { SVG } from 'mathjax-full/js/output/svg.js'

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

export const NotebookNodeLatex = Node.create({
    name: 'latexBlock',
    group: 'block',
    atom: true,
    selectable: true,
    content: 'text*',
    parseHTML() {
        return [
            {
                tag: 'div[data-latex-block]',
            },
        ]
    },
    renderHTML({ HTMLAttributes, node }) {
        const content = node.textContent || ''
        return [
            'div',
            mergeAttributes(HTMLAttributes, {
                class: 'NotebookLatex',
                'data-latex-block': true,
                style: 'text-align: center;',
            }),
            content,
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
                    const start = range.from + (match[0].startsWith(' ') ? 2 : 0)
                    const end = range.to - (match[0].endsWith(' ') ? 2 : 0)
                    chain()
                        .deleteRange({ from: start, to: end })
                        .insertContent({ type: 'latexBlock', content: [{ type: 'text', text: latex }] })
                        .run()
                },
            }),
        ]
    },
    addProseMirrorPlugins() {
        return [
            new Plugin({
                key: new PluginKey('latexBlock'),
                view: (view: EditorView) => {
                    return {
                        update: () => {
                            setTimeout(() => {
                                const latexElements = view.dom.querySelectorAll('.NotebookLatex')
                                latexElements.forEach((el: Element) => {
                                    const element = el as HTMLElement
                                    const content = element.textContent || ''
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
                                    }
                                })
                            }, 0)
                        },
                    }
                },
            }),
        ]
    },
})
