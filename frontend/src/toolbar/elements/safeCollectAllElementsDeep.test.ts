import { safeCollectAllElementsDeep } from './safeCollectAllElementsDeep'

function createContainer(html: string): { container: HTMLElement; cleanup: () => void } {
    const container = document.createElement('div')
    container.innerHTML = html
    document.body.appendChild(container)
    return {
        container,
        cleanup: () => {
            document.body.removeChild(container)
        },
    }
}

function makeShadowRootThrow(element: Element, error: Error): void {
    Object.defineProperty(element, 'shadowRoot', {
        configurable: true,
        get() {
            throw error
        },
    })
}

describe('safeCollectAllElementsDeep', () => {
    it('collects all elements in a flat document', () => {
        const { container, cleanup } = createContainer('<div id="a"></div><span id="b"></span>')
        try {
            const elements = safeCollectAllElementsDeep(document)
            expect(elements).toContain(container.querySelector('#a'))
            expect(elements).toContain(container.querySelector('#b'))
        } finally {
            cleanup()
        }
    })

    it('descends into open shadow roots', () => {
        const { container, cleanup } = createContainer('<div id="host"></div>')
        try {
            const host = container.querySelector('#host') as HTMLElement
            const shadow = host.attachShadow({ mode: 'open' })
            const shadowChild = document.createElement('button')
            shadowChild.id = 'shadow-child'
            shadow.appendChild(shadowChild)

            const elements = safeCollectAllElementsDeep(document)
            expect(elements).toContain(host)
            expect(elements).toContain(shadowChild)
        } finally {
            cleanup()
        }
    })

    it('returns elements collected so far when shadowRoot access throws (cross-origin iframe)', () => {
        const { container, cleanup } = createContainer(
            '<div id="before"></div><iframe id="cross-origin"></iframe><div id="after"></div>'
        )
        try {
            const iframe = container.querySelector('#cross-origin') as HTMLIFrameElement
            makeShadowRootThrow(
                iframe,
                new DOMException('Permission denied to access property "shadowRoot"', 'SecurityError')
            )

            const before = container.querySelector('#before')
            const after = container.querySelector('#after')

            let elements: HTMLElement[] = []
            expect(() => {
                elements = safeCollectAllElementsDeep(document)
            }).not.toThrow()

            expect(elements).toContain(before)
            expect(elements).toContain(iframe)
            expect(elements).toContain(after)
        } finally {
            cleanup()
        }
    })

    it('continues collecting siblings when one element shadowRoot access throws', () => {
        const { container, cleanup } = createContainer('<div id="one"></div><div id="two"></div><div id="three"></div>')
        try {
            const two = container.querySelector('#two') as HTMLElement
            makeShadowRootThrow(two, new Error('boom'))

            const elements = safeCollectAllElementsDeep(document)
            expect(elements).toContain(container.querySelector('#one'))
            expect(elements).toContain(two)
            expect(elements).toContain(container.querySelector('#three'))
        } finally {
            cleanup()
        }
    })
})
