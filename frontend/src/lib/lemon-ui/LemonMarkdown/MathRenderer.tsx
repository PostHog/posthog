import { useEffect, useRef } from 'react'
import { browserAdaptor } from 'mathjax-full/js/adaptors/browserAdaptor.js'
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js'
import { TeX } from 'mathjax-full/js/input/tex.js'
import { mathjax } from 'mathjax-full/js/mathjax.js'
import { SVG } from 'mathjax-full/js/output/svg.js'

let mathJaxInstance: any = null

function initMathJax(): any {
    if (!mathJaxInstance) {
        RegisterHTMLHandler(browserAdaptor())
        const tex = new TeX({
            packages: ['base', 'ams'],
            inlineMath: [['$', '$']],
            displayMath: [['$$', '$$']],
            processEscapes: true,
            processEnvironments: true,
        })
        const svg = new SVG({ fontCache: 'none' })
        mathJaxInstance = mathjax.document(document, { InputJax: tex, OutputJax: svg })
    }
    return mathJaxInstance
}

interface MathRendererProps {
    children: string
    block?: boolean
}

export function MathRenderer({ children, block = false }: MathRendererProps): JSX.Element {
    const containerRef = useRef<HTMLSpanElement>(null)

    useEffect(() => {
        const container = containerRef.current
        if (!container || !children) {
            return
        }

        try {
            const mjxDocument = initMathJax()
            container.innerHTML = '' // Clear previous content
            const math = mjxDocument.convert(children, { display: block })
            container.appendChild(math)
        } catch (err) {
            console.error('MathJax error:', err)
            container.innerHTML = `<span style="color: red; font-family: monospace;">${children}</span>`
        }
    }, [children, block])

    return (
        <span
            ref={containerRef}
            className={`math-renderer ${block ? 'math-block' : 'math-inline'}`}
            style={{
                display: block ? 'block' : 'inline',
                textAlign: block ? 'center' : 'inherit',
                margin: block ? '1em 0' : '0',
            }}
        />
    )
}
