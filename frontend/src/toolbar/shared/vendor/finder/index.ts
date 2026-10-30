// Vendored from @medv/finder@4.0.2 — https://github.com/antonmedv/finder
// Ported in place (TypeScript, no formatting reflow) so we can carry a fix that
// is still unmerged upstream.
//
// PostHog modifications:
//   - Guard against combinatorial explosion before materializing the candidate
//     paths in `search()`. On DOMs with many classes across many levels the
//     cross-product of `combinations(stack)` can reach hundreds of millions of
//     entries and exhaust memory / overflow the stack *before* the timeout and
//     `maxNumberOfPathChecks` guards in `finder()` ever run. We compute the
//     product of the level sizes (cheap) and stop expanding once it exceeds
//     `maxCombinations`. Adapted from upstream antonmedv/finder#84, the fix for
//     antonmedv/finder#85.
//   - Append candidates with an iterative `for...of` push instead of
//     `paths.push(...combinations(stack))`. Spreading a generator's output as
//     function arguments is itself bounded by the engine's argument-count limit
//     (~65k), so the spread form would reintroduce a crash if `maxCombinations`
//     were ever raised past that ceiling — the same failure class the guard
//     above exists to prevent. The iterative push has no such ceiling and emits
//     identical candidates in identical order.
//   - Added an optional `onCombinationsCapped` callback so callers can observe
//     when the guard trips (cutting the candidate search short, which may force
//     a positional fallback) without coupling this vendored file to any PostHog
//     logging. It receives the level count reached so callers can record how
//     deep the offending element was.
//
// MIT License
//
// Copyright (c) 2018 Anton Medvedev
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

type Knot = {
    name: string
    penalty: number
    level?: number
}

const acceptedAttrNames = new Set(['role', 'name', 'aria-label', 'rel', 'href'])

/** Check if attribute name and value are word-like. */
export function attr(name: string, value: string): boolean {
    let nameIsOk = acceptedAttrNames.has(name)
    nameIsOk ||= name.startsWith('data-') && wordLike(name)

    let valueIsOk = wordLike(value) && value.length < 100
    valueIsOk ||= value.startsWith('#') && wordLike(value.slice(1))

    return nameIsOk && valueIsOk
}

/** Check if id name is word-like. */
export function idName(name: string): boolean {
    return wordLike(name)
}

/** Check if class name is word-like. */
export function className(name: string): boolean {
    return wordLike(name)
}

/** Check if tag name is word-like. */
export function tagName(_name: string): boolean {
    return true
}

/** Configuration options for the finder. */
export type Options = {
    /** The root element to start the search from. */
    root: Element
    /** Function that determines if an id name may be used in a selector. */
    idName: (name: string) => boolean
    /** Function that determines if a class name may be used in a selector. */
    className: (name: string) => boolean
    /** Function that determines if a tag name may be used in a selector. */
    tagName: (name: string) => boolean
    /** Function that determines if an attribute may be used in a selector. */
    attr: (name: string, value: string) => boolean
    /** Timeout to search for a selector. */
    timeoutMs: number
    /** Minimum length of levels in fining selector. */
    seedMinLength: number
    /** Minimum length for optimising selector. */
    optimizedMinLength: number
    /** Maximum number of path checks. */
    maxNumberOfPathChecks: number
    /**
     * PostHog addition: maximum size of the candidate cross-product to
     * materialize per search level. Caps the combinatorial blow-up described in
     * antonmedv/finder#85 before it can exhaust memory. Defaults to a value far
     * above what normal elements ever need, so it only trips on pathological DOMs.
     */
    maxCombinations: number
    /**
     * PostHog addition: invoked when `maxCombinations` is exceeded and the
     * candidate search is cut short — which may force a positional fallback, but
     * a stable selector found before the cap can still win. Receives the number
     * of levels (ancestor depth) reached when the guard tripped. Optional and
     * side-effect-only; lets callers emit a signal without this vendored file
     * depending on any logging.
     */
    onCombinationsCapped?: (info: { levels: number }) => void
}

/** Finds unique CSS selectors for the given element. */
export function finder(input: Element, options?: Partial<Options>): string {
    if (input.nodeType !== Node.ELEMENT_NODE) {
        throw new Error(`Can't generate CSS selector for non-element node type.`)
    }
    if (input.tagName.toLowerCase() === 'html') {
        return 'html'
    }
    const defaults: Options = {
        root: document.body,
        idName: idName,
        className: className,
        tagName: tagName,
        attr: attr,
        timeoutMs: 1000,
        seedMinLength: 3,
        optimizedMinLength: 2,
        maxNumberOfPathChecks: Infinity,
        maxCombinations: 50_000,
    }

    const startTime = new Date()
    const config = { ...defaults, ...options }
    const rootDocument = findRootDocument(config.root, defaults)

    let foundPath: Knot[] | undefined
    let count = 0
    for (const candidate of search(input, config, rootDocument)) {
        const elapsedTimeMs = new Date().getTime() - startTime.getTime()
        if (elapsedTimeMs > config.timeoutMs || count >= config.maxNumberOfPathChecks) {
            const fPath = fallback(input, rootDocument)
            if (!fPath) {
                throw new Error(`Timeout: Can't find a unique selector after ${config.timeoutMs}ms`)
            }
            return selector(fPath)
        }
        count++
        if (unique(candidate, rootDocument)) {
            foundPath = candidate
            break
        }
    }

    if (!foundPath) {
        // PostHog: when the combinatorial guard in `search()` cuts the walk short
        // there may be no unique short selector. Fall back to a positional
        // nth-of-type path (matching upstream antonmedv/finder#84's "return
        // fallback" behaviour) so callers still get a working selector instead of
        // an exception.
        const fPath = fallback(input, rootDocument)
        if (fPath) {
            return selector(fPath)
        }
        throw new Error(`Selector was not found.`)
    }

    const optimized = [...optimize(foundPath, input, config, rootDocument, startTime)]
    optimized.sort(byPenalty)
    if (optimized.length > 0) {
        return selector(optimized[0])
    }
    return selector(foundPath)
}

function* search(input: Element, config: Options, rootDocument: Element | Document): Generator<Knot[]> {
    const stack: Knot[][] = []
    let paths: Knot[][] = []
    let current: Element | null = input
    let i = 0
    while (current && current !== rootDocument) {
        const level = tie(current, config)
        for (const node of level) {
            node.level = i
        }
        stack.push(level)
        current = current.parentElement
        i++

        // PostHog: bail before the cross-product explodes (antonmedv/finder#85).
        // The product of level sizes is the number of paths `combinations(stack)`
        // would emit; computing it is O(levels) and lets us stop before the
        // O(product) materialization below allocates an unbounded array.
        const numCombinations = stack.reduce((product, levelKnots) => product * levelKnots.length, 1)
        if (numCombinations > config.maxCombinations) {
            config.onCombinationsCapped?.({ levels: stack.length })
            break
        }

        for (const candidate of combinations(stack)) {
            paths.push(candidate)
        }

        if (i >= config.seedMinLength) {
            paths.sort(byPenalty)
            for (const candidate of paths) {
                yield candidate
            }
            paths = []
        }
    }

    paths.sort(byPenalty)
    for (const candidate of paths) {
        yield candidate
    }
}

function wordLike(name: string): boolean {
    if (/^[a-z-]{3,}$/i.test(name)) {
        const words = name.split(/-|[A-Z]/)
        for (const word of words) {
            if (word.length <= 2) {
                return false
            }
            if (/[^aeiou]{4,}/i.test(word)) {
                return false
            }
        }
        return true
    }
    return false
}

function tie(element: Element, config: Options): Knot[] {
    const level: Knot[] = []

    const elementId = element.getAttribute('id')
    if (elementId && config.idName(elementId)) {
        level.push({
            name: '#' + CSS.escape(elementId),
            penalty: 0,
        })
    }

    for (let i = 0; i < element.classList.length; i++) {
        const name = element.classList[i]
        if (config.className(name)) {
            level.push({
                name: '.' + CSS.escape(name),
                penalty: 1,
            })
        }
    }

    for (let i = 0; i < element.attributes.length; i++) {
        const attr = element.attributes[i]
        if (config.attr(attr.name, attr.value)) {
            level.push({
                name: `[${CSS.escape(attr.name)}="${CSS.escape(attr.value)}"]`,
                penalty: 2,
            })
        }
    }

    const tagName = element.tagName.toLowerCase()
    if (config.tagName(tagName)) {
        level.push({
            name: tagName,
            penalty: 5,
        })

        const index = indexOf(element, tagName)
        if (index !== undefined) {
            level.push({
                name: nthOfType(tagName, index),
                penalty: 10,
            })
        }
    }

    const nth = indexOf(element)
    if (nth !== undefined) {
        level.push({
            name: nthChild(tagName, nth),
            penalty: 50,
        })
    }

    return level
}

function selector(path: Knot[]): string {
    let node = path[0]
    let query = node.name
    for (let i = 1; i < path.length; i++) {
        const level = path[i].level || 0
        if (node.level === level - 1) {
            query = `${path[i].name} > ${query}`
        } else {
            query = `${path[i].name} ${query}`
        }
        node = path[i]
    }
    return query
}

function penalty(path: Knot[]): number {
    return path.map((node) => node.penalty).reduce((acc, i) => acc + i, 0)
}

function byPenalty(a: Knot[], b: Knot[]): number {
    return penalty(a) - penalty(b)
}

function indexOf(input: Element, tagName?: string): number | undefined {
    const parent = input.parentNode
    if (!parent) {
        return undefined
    }
    let child = parent.firstChild
    if (!child) {
        return undefined
    }
    let i = 0
    while (child) {
        if (
            child.nodeType === Node.ELEMENT_NODE &&
            (tagName === undefined || (child as Element).tagName.toLowerCase() === tagName)
        ) {
            i++
        }
        if (child === input) {
            break
        }
        child = child.nextSibling
    }
    return i
}

function fallback(input: Element, rootDocument: Element | Document): Knot[] | undefined {
    let i = 0
    let current: Element | null = input
    const path: Knot[] = []
    while (current && current !== rootDocument) {
        const tagName = current.tagName.toLowerCase()
        const index = indexOf(current, tagName)
        if (index === undefined) {
            return
        }
        path.push({
            name: nthOfType(tagName, index),
            penalty: NaN,
            level: i,
        })
        current = current.parentElement
        i++
    }
    if (unique(path, rootDocument)) {
        return path
    }
}

function nthChild(tagName: string, index: number): string {
    if (tagName === 'html') {
        return 'html'
    }
    return `${tagName}:nth-child(${index})`
}

function nthOfType(tagName: string, index: number): string {
    if (tagName === 'html') {
        return 'html'
    }
    return `${tagName}:nth-of-type(${index})`
}

function* combinations(stack: Knot[][], path: Knot[] = []): Generator<Knot[]> {
    if (stack.length > 0) {
        for (const node of stack[0]) {
            yield* combinations(stack.slice(1, stack.length), path.concat(node))
        }
    } else {
        yield path
    }
}

function findRootDocument(rootNode: Element | Document, defaults: Options): Element | Document {
    if (rootNode.nodeType === Node.DOCUMENT_NODE) {
        return rootNode
    }
    if (rootNode === defaults.root) {
        return rootNode.ownerDocument as Document
    }
    return rootNode
}

function unique(path: Knot[], rootDocument: Element | Document): boolean {
    const css = selector(path)
    switch (rootDocument.querySelectorAll(css).length) {
        case 0:
            throw new Error(`Can't select any node with this selector: ${css}`)
        case 1:
            return true
        default:
            return false
    }
}

function* optimize(
    path: Knot[],
    input: Element,
    config: Options,
    rootDocument: Element | Document,
    startTime: Date
): Generator<Knot[]> {
    if (path.length > 2 && path.length > config.optimizedMinLength) {
        for (let i = 1; i < path.length - 1; i++) {
            const elapsedTimeMs = new Date().getTime() - startTime.getTime()
            if (elapsedTimeMs > config.timeoutMs) {
                return
            }
            const newPath = [...path]
            newPath.splice(i, 1)
            if (unique(newPath, rootDocument) && rootDocument.querySelector(selector(newPath)) === input) {
                yield newPath
                yield* optimize(newPath, input, config, rootDocument, startTime)
            }
        }
    }
}
