import { finder } from './index'

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

    it('generates a unique selector that matches the element', () => {
        document.body.innerHTML = `
            <div class="container">
                <ul class="menu">
                    <li class="item">first</li>
                    <li class="target">second</li>
                </ul>
            </div>
        `
        const target = document.querySelector('.target')!

        const selector = finder(target)

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

        expect(document.querySelector(selector)).toBe(target)
    })

    it('honours an explicit maxCombinations cap and still returns a working selector', () => {
        document.body.innerHTML = `
            <section class="alpha bravo charlie">
                <article class="delta echo foxtrot">
                    <span class="golf hotel india">target</span>
                </article>
            </section>
        `
        const target = document.querySelector('.golf')!

        // A cap of 1 forces the guard to trip on the first level, so finder must
        // fall back rather than enumerate selectors — but still produce a match.
        const selector = finder(target, { maxCombinations: 1 })

        expect(document.querySelector(selector)).toBe(target)
    })
})
