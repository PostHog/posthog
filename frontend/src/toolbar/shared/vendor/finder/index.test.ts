import { finder } from './index'

// A small class-heavy tree whose first level alone carries enough word-like
// classes that `maxCombinations: 1` trips the guard immediately.
const CAPPABLE_HTML = `
    <section class="alpha bravo charlie">
        <article class="delta echo foxtrot">
            <span class="golf hotel india">target</span>
        </article>
    </section>
`

describe('vendored finder', () => {
    afterEach(() => {
        document.body.innerHTML = ''
    })

    function deepestChild(): Element {
        let element: Element = document.body
        while (element.firstElementChild) {
            element = element.firstElementChild
        }
        return element
    }

    it.each([
        {
            name: 'generates a unique selector that matches the element',
            html: `
                <div class="container">
                    <ul class="menu">
                        <li class="item">first</li>
                        <li class="target">second</li>
                    </ul>
                </div>
            `,
            targetSelector: '.target',
            config: undefined,
        },
        {
            name: 'honours an explicit maxCombinations cap and still returns a working selector',
            // A cap of 1 forces the guard to trip on the first level, so finder must
            // fall back rather than enumerate selectors — but still produce a match.
            html: CAPPABLE_HTML,
            targetSelector: '.golf',
            config: { maxCombinations: 1 },
        },
    ])('$name', ({ html, targetSelector, config }) => {
        document.body.innerHTML = html
        const target = document.querySelector(targetSelector)!

        const selector = config ? finder(target, config) : finder(target)

        expect(document.querySelectorAll(selector)).toHaveLength(1)
        expect(document.querySelector(selector)).toBe(target)
    })

    it('does not blow up on many classes across many levels (antonmedv/finder#85)', () => {
        // Every level carries many word-like classes, so the naive cross-product
        // of candidate selectors reaches hundreds of millions of paths. Without
        // the combination guard this exhausts memory / times the test out; with
        // it, finder falls back to a positional path and returns promptly.
        const classes = ['alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot', 'golf', 'hotel', 'india', 'juliet']
        let html = 'target'
        for (let depth = 0; depth < 12; depth++) {
            html = `<div class="${classes.join(' ')}">${html}</div>`
        }
        document.body.innerHTML = html
        const target = deepestChild()

        const selector = finder(target)

        expect(document.querySelectorAll(selector)).toHaveLength(1)
        expect(document.querySelector(selector)).toBe(target)
    }, 5_000)

    it.each([
        { name: 'does not fire onCombinationsCapped under the default cap', config: {}, expectedCalls: 0 },
        {
            name: 'fires onCombinationsCapped exactly once when the cap trips',
            config: { maxCombinations: 1 },
            expectedCalls: 1,
        },
    ])('$name', ({ config, expectedCalls }) => {
        document.body.innerHTML = CAPPABLE_HTML
        const target = document.querySelector('.golf')!

        const cappedSpy = jest.fn()
        finder(target, { ...config, onCombinationsCapped: cappedSpy })

        expect(cappedSpy).toHaveBeenCalledTimes(expectedCalls)
    })

    it('passes the level count to onCombinationsCapped when the cap trips', () => {
        document.body.innerHTML = CAPPABLE_HTML
        const target = document.querySelector('.golf')!

        const cappedSpy = jest.fn()
        finder(target, { maxCombinations: 1, onCombinationsCapped: cappedSpy })

        expect(cappedSpy).toHaveBeenCalledWith({ levels: expect.any(Number) })
    })
})
