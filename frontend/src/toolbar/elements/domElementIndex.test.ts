import { collectAllElementsDeep, querySelectorAllDeep } from 'query-selector-shadow-dom'

import { elementToSelector } from 'lib/actionUtils'

import { CountedHTMLElement, ElementsEventType } from '~/toolbar/types'

import { buildDOMIndex, matchEventToElementUsingIndex } from './domElementIndex'

function matchEventToElementOriginal(
    event: ElementsEventType,
    dataAttributes: string[],
    matchLinksByHref: boolean,
    pageElements: HTMLElement[],
    selectorCache: Record<string, HTMLElement[]>
): CountedHTMLElement | null {
    let lastSelector: string | undefined

    for (let i = 0; i < event.elements.length; i++) {
        const element = event.elements[i]
        const selector =
            elementToSelector(matchLinksByHref ? element : { ...element, href: undefined }, dataAttributes) || '*'
        const combinedSelector = lastSelector ? `${selector} > ${lastSelector}` : selector

        try {
            let domElements: HTMLElement[] | undefined = selectorCache[combinedSelector]
            if (domElements === undefined) {
                domElements = Array.from(querySelectorAllDeep(combinedSelector, document, pageElements))
                selectorCache[combinedSelector] = domElements
            }

            if (domElements.length === 1) {
                const e = event.elements[i]
                const isTooSimple =
                    i === 0 &&
                    e.tag_name &&
                    !e.attr_class &&
                    !e.attr_id &&
                    !e.href &&
                    !e.text &&
                    e.nth_child === 1 &&
                    e.nth_of_type === 1 &&
                    !e.attributes['attr__data-attr']

                if (!isTooSimple) {
                    return {
                        element: domElements[0],
                        count: event.count,
                        selector: selector,
                        hash: event.hash,
                        type: event.type,
                        clickCount: 0,
                        rageclickCount: 0,
                        deadclickCount: 0,
                    }
                }
            }

            if (domElements.length === 0) {
                if (i === event.elements.length - 1) {
                    return null
                } else if (i > 0 && lastSelector) {
                    lastSelector = `* > ${lastSelector}`
                    continue
                }
            }
        } catch {
            break
        }

        lastSelector = combinedSelector
    }

    return null
}

function createTestDOM(html: string): { container: HTMLElement; cleanup: () => void } {
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

function getAllElements(container: HTMLElement): HTMLElement[] {
    return Array.from(container.querySelectorAll('*')) as HTMLElement[]
}

describe('domElementIndex', () => {
    describe('buildDOMIndex', () => {
        const indexByIdCases = [
            {
                name: 'indexes single element by id',
                html: '<div id="test-id"></div>',
                id: 'test-id',
                expectedCount: 1,
            },
            {
                name: 'indexes multiple elements with same id',
                html: '<div id="dup"></div><span id="dup"></span>',
                id: 'dup',
                expectedCount: 2,
            },
        ]

        it.each(indexByIdCases)('$name', ({ html, id, expectedCount }) => {
            const { container, cleanup } = createTestDOM(html)
            try {
                const index = buildDOMIndex(getAllElements(container))
                expect(index.byId.get(id)?.length).toBe(expectedCount)
            } finally {
                cleanup()
            }
        })

        const indexByTagNameCases = [
            {
                name: 'indexes elements by tag name',
                html: '<div></div><div></div><span></span>',
                tag: 'div',
                expectedCount: 2,
            },
            {
                name: 'indexes tag names case-insensitively',
                html: '<DIV></DIV><div></div>',
                tag: 'div',
                expectedCount: 2,
            },
        ]

        it.each(indexByTagNameCases)('$name', ({ html, tag, expectedCount }) => {
            const { container, cleanup } = createTestDOM(html)
            try {
                const index = buildDOMIndex(getAllElements(container))
                expect(index.byTagName.get(tag)?.length).toBe(expectedCount)
            } finally {
                cleanup()
            }
        })

        const indexByClassCases = [
            {
                name: 'indexes elements by class',
                html: '<div class="foo"></div><div class="foo bar"></div>',
                className: 'foo',
                expectedCount: 2,
            },
            {
                name: 'indexes each class separately',
                html: '<div class="a b c"></div>',
                className: 'b',
                expectedCount: 1,
            },
        ]

        it.each(indexByClassCases)('$name', ({ html, className, expectedCount }) => {
            const { container, cleanup } = createTestDOM(html)
            try {
                const index = buildDOMIndex(getAllElements(container))
                expect(index.byClass.get(className)?.length).toBe(expectedCount)
            } finally {
                cleanup()
            }
        })

        const indexByDataAttrCases = [
            {
                name: 'indexes elements by data attribute',
                html: '<div data-testid="button"></div>',
                attrName: 'data-testid',
                attrValue: 'button',
                expectedCount: 1,
            },
            {
                name: 'indexes multiple elements with same data attribute value',
                html: '<div data-testid="item"></div><span data-testid="item"></span>',
                attrName: 'data-testid',
                attrValue: 'item',
                expectedCount: 2,
            },
        ]

        it.each(indexByDataAttrCases)('$name', ({ html, attrName, attrValue, expectedCount }) => {
            const { container, cleanup } = createTestDOM(html)
            try {
                const index = buildDOMIndex(getAllElements(container))
                expect(index.byDataAttr.get(attrName)?.get(attrValue)?.length).toBe(expectedCount)
            } finally {
                cleanup()
            }
        })

        it('stores fingerprints with correct nth-child and nth-of-type', () => {
            const { container, cleanup } = createTestDOM(
                '<ul><li></li><li id="target"></li><span></span><li></li></ul>'
            )
            try {
                const index = buildDOMIndex(getAllElements(container))
                const target = container.querySelector('#target') as HTMLElement
                const fingerprint = index.fingerprints.get(target)

                expect(fingerprint?.nthChild).toBe(2)
                expect(fingerprint?.nthOfType).toBe(2)
            } finally {
                cleanup()
            }
        })
    })

    describe('matchEventToElementUsingIndex', () => {
        function createEvent(
            elements: Partial<ElementsEventType['elements'][0]>[],
            overrides?: Partial<ElementsEventType>
        ): ElementsEventType {
            return {
                count: 1,
                hash: 'test-hash',
                type: '$autocapture',
                elements: elements.map((el) => ({
                    tag_name: 'div',
                    attributes: {},
                    ...el,
                })),
                ...overrides,
            }
        }

        const matchByIdCases = [
            {
                name: 'matches element by id',
                html: '<div id="target"></div><div></div>',
                event: { attr_id: 'target' },
                shouldMatch: true,
            },
            {
                name: 'returns null when id not found',
                html: '<span id="other"></span>',
                event: { attr_id: 'nonexistent', tag_name: 'button' },
                shouldMatch: false,
            },
        ]

        it.each(matchByIdCases)('$name', ({ html, event, shouldMatch }) => {
            const { container, cleanup } = createTestDOM(html)
            try {
                const index = buildDOMIndex(getAllElements(container))
                const result = matchEventToElementUsingIndex(createEvent([event]), [], false, index)

                if (shouldMatch) {
                    expect(result).not.toBeNull()
                    expect(result?.element.id).toBe(event.attr_id)
                } else {
                    expect(result).toBeNull()
                }
            } finally {
                cleanup()
            }
        })

        const matchByClassCases = [
            {
                name: 'matches element by single class',
                html: '<div class="target"></div><div class="other"></div>',
                event: { tag_name: 'div', attr_class: ['target'] },
                shouldMatch: true,
            },
            {
                name: 'matches element by multiple classes',
                html: '<div class="a b c"></div><div class="a"></div>',
                event: { tag_name: 'div', attr_class: ['a', 'b'] },
                shouldMatch: true,
            },
            {
                name: 'returns null when class combination not found',
                html: '<div class="a"></div><div class="b"></div>',
                event: { tag_name: 'div', attr_class: ['a', 'b'] },
                shouldMatch: false,
            },
        ]

        it.each(matchByClassCases)('$name', ({ html, event, shouldMatch }) => {
            const { container, cleanup } = createTestDOM(html)
            try {
                const index = buildDOMIndex(getAllElements(container))
                const result = matchEventToElementUsingIndex(createEvent([event]), [], false, index)

                if (shouldMatch) {
                    expect(result).not.toBeNull()
                } else {
                    expect(result).toBeNull()
                }
            } finally {
                cleanup()
            }
        })

        const nthChildCases = [
            {
                name: 'filters by nth-child position',
                html: '<ul><li></li><li id="target"></li><li></li></ul>',
                event: { tag_name: 'li', nth_child: 2 },
                expectedId: 'target',
            },
            {
                name: 'filters by nth-of-type position',
                html: '<div><span></span><p></p><span id="target"></span></div>',
                event: { tag_name: 'span', nth_of_type: 2 },
                expectedId: 'target',
            },
        ]

        it.each(nthChildCases)('$name', ({ html, event, expectedId }) => {
            const { container, cleanup } = createTestDOM(html)
            try {
                const index = buildDOMIndex(getAllElements(container))
                const result = matchEventToElementUsingIndex(createEvent([event]), [], false, index)

                expect(result).not.toBeNull()
                expect(result?.element.id).toBe(expectedId)
            } finally {
                cleanup()
            }
        })

        it('uses parent chain to disambiguate multiple candidates', () => {
            const { container, cleanup } = createTestDOM(`
                <div class="container-a"><button class="btn"></button></div>
                <div class="container-b"><button class="btn" id="target"></button></div>
            `)
            try {
                const index = buildDOMIndex(getAllElements(container))
                const event = createEvent([
                    { tag_name: 'button', attr_class: ['btn'] },
                    { tag_name: 'div', attr_class: ['container-b'] },
                ])
                const result = matchEventToElementUsingIndex(event, [], false, index)

                expect(result).not.toBeNull()
                expect(result?.element.id).toBe('target')
            } finally {
                cleanup()
            }
        })

        it('applies isTooSimple check for generic elements', () => {
            const { container, cleanup } = createTestDOM('<div><div></div></div>')
            try {
                const index = buildDOMIndex(getAllElements(container))
                const event = createEvent([{ tag_name: 'div', nth_child: 1, nth_of_type: 1 }])
                const result = matchEventToElementUsingIndex(event, [], false, index)

                expect(result).toBeNull()
            } finally {
                cleanup()
            }
        })

        it('does not apply isTooSimple check when element has class', () => {
            const { container, cleanup } = createTestDOM('<div><div class="content"></div></div>')
            try {
                const index = buildDOMIndex(getAllElements(container))
                const event = createEvent([{ tag_name: 'div', attr_class: ['content'], nth_child: 1, nth_of_type: 1 }])
                const result = matchEventToElementUsingIndex(event, [], false, index)

                expect(result).not.toBeNull()
            } finally {
                cleanup()
            }
        })

        it('returns null for empty elements array', () => {
            const { container, cleanup } = createTestDOM('<div></div>')
            try {
                const index = buildDOMIndex(getAllElements(container))
                const event = createEvent([])
                const result = matchEventToElementUsingIndex(event, [], false, index)

                expect(result).toBeNull()
            } finally {
                cleanup()
            }
        })

        it('preserves event count and type in result', () => {
            const { container, cleanup } = createTestDOM('<div id="target"></div>')
            try {
                const index = buildDOMIndex(getAllElements(container))
                const event = createEvent([{ attr_id: 'target' }], { count: 42, type: '$rageclick' })
                const result = matchEventToElementUsingIndex(event, [], false, index)

                expect(result?.count).toBe(42)
                expect(result?.type).toBe('$rageclick')
            } finally {
                cleanup()
            }
        })
    })

    describe('index-based vs selector-based matching comparison', () => {
        function createEvent(
            elements: Partial<ElementsEventType['elements'][0]>[],
            overrides?: Partial<ElementsEventType>
        ): ElementsEventType {
            return {
                count: 1,
                hash: 'test-hash',
                type: '$autocapture',
                elements: elements.map((el) => ({
                    tag_name: 'div',
                    attributes: {},
                    ...el,
                })),
                ...overrides,
            }
        }

        const comparisonCases = [
            {
                name: 'matches button by id',
                html: '<button id="submit-btn">Submit</button>',
                event: [{ tag_name: 'button', attr_id: 'submit-btn', text: 'Submit' }],
            },
            {
                name: 'matches link by class and href',
                html: '<a class="nav-link" href="/home">Home</a>',
                event: [{ tag_name: 'a', attr_class: ['nav-link'], href: '/home' }],
            },
            {
                name: 'matches nested element with parent chain',
                html: `
                    <div class="card">
                        <div class="card-body">
                            <button class="btn btn-primary">Click</button>
                        </div>
                    </div>
                `,
                event: [
                    { tag_name: 'button', attr_class: ['btn', 'btn-primary'] },
                    { tag_name: 'div', attr_class: ['card-body'] },
                    { tag_name: 'div', attr_class: ['card'] },
                ],
            },
            {
                name: 'matches element by nth-child in list',
                html: '<ul><li>One</li><li id="target">Two</li><li>Three</li></ul>',
                event: [
                    { tag_name: 'li', nth_child: 2, nth_of_type: 2 },
                    { tag_name: 'ul', nth_child: 1, nth_of_type: 1 },
                ],
            },
            {
                name: 'matches input by type attribute',
                html: '<input type="email" class="form-control" id="email-input">',
                event: [{ tag_name: 'input', attr_id: 'email-input', attr_class: ['form-control'] }],
            },
            {
                name: 'does not match when element missing',
                html: '<div class="container"></div>',
                event: [{ tag_name: 'button', attr_class: ['missing'] }],
            },
            {
                name: 'matches data-testid element',
                html: '<button data-testid="cta-button">Click me</button>',
                event: [{ tag_name: 'button', attributes: { 'attr__data-testid': 'cta-button' } }],
                dataAttributes: ['data-testid'],
            },
        ]

        it.each(comparisonCases)('$name: both implementations agree', ({ html, event, dataAttributes = [] }) => {
            const { cleanup } = createTestDOM(html)
            try {
                const pageElements = collectAllElementsDeep('*', document) as HTMLElement[]
                const index = buildDOMIndex(pageElements)
                const selectorCache: Record<string, HTMLElement[]> = {}

                const eventObj = createEvent(event)

                const indexResult = matchEventToElementUsingIndex(eventObj, dataAttributes, true, index)
                const originalResult = matchEventToElementOriginal(
                    eventObj,
                    dataAttributes,
                    true,
                    pageElements,
                    selectorCache
                )

                if (originalResult === null) {
                    expect(indexResult).toBeNull()
                } else {
                    expect(indexResult).not.toBeNull()
                    expect(indexResult?.element).toBe(originalResult.element)
                    expect(indexResult?.count).toBe(originalResult.count)
                    expect(indexResult?.hash).toBe(originalResult.hash)
                }
            } finally {
                cleanup()
            }
        })
    })
})
