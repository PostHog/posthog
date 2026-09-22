import { collectAllElementsDeep } from 'query-selector-shadow-dom'

import { ElementsEventType } from '~/toolbar/types'
import { ElementType } from '~/types'

import {
    buildDOMIndex,
    matchEventToElementUsingIndex,
    matchEventToElementUsingSelectors,
    matchIsChainConsistent,
} from './domElementIndex'

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
                const result = matchEventToElementUsingIndex(createEvent([event]), index)

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
                const result = matchEventToElementUsingIndex(createEvent([event]), index)

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
                const result = matchEventToElementUsingIndex(createEvent([event]), index)

                expect(result).not.toBeNull()
                expect(result?.element.id).toBe(expectedId)
            } finally {
                cleanup()
            }
        })

        const parentChainCases = [
            {
                name: 'uses parent chain to disambiguate multiple candidates',
                html: `
                    <div class="container-a"><button class="btn"></button></div>
                    <div class="container-b"><button class="btn" id="target"></button></div>
                `,
                event: [
                    { tag_name: 'button', attr_class: ['btn'] },
                    { tag_name: 'div', attr_class: ['container-b'] },
                ],
            },
            {
                name: 'uses ancestor position to disambiguate repeated identical structures',
                html: `
                    <div class="row"><button class="btn"></button></div>
                    <div class="row"><button class="btn" id="target"></button></div>
                    <div class="row"><button class="btn"></button></div>
                `,
                event: [
                    { tag_name: 'button', attr_class: ['btn'], nth_child: 1, nth_of_type: 1 },
                    { tag_name: 'div', attr_class: ['row'], nth_child: 2, nth_of_type: 2 },
                ],
            },
            {
                name: 'walks one ancestor level per chain entry, not the parent repeatedly',
                html: `
                    <section class="outer-a"><div class="middle"><button class="btn"></button></div></section>
                    <section class="outer-b"><div class="middle"><button class="btn" id="target"></button></div></section>
                `,
                event: [
                    { tag_name: 'button', attr_class: ['btn'] },
                    { tag_name: 'div', attr_class: ['middle'] },
                    { tag_name: 'section', attr_class: ['outer-b'] },
                ],
            },
            {
                name: 'uses position to pick between siblings sharing a data attribute',
                html: `
                    <div>
                        <button data-attr="cta"></button>
                        <button data-attr="cta" id="target"></button>
                    </div>
                `,
                event: [
                    {
                        tag_name: 'button',
                        attributes: { 'attr__data-attr': 'cta' },
                        nth_child: 2,
                        nth_of_type: 2,
                    },
                ],
                dataAttributes: ['data-attr'],
            },
            {
                name: 'ignores drifted sibling position when the clicked element is identified by id',
                html: `
                    <div class="injected-banner"></div>
                    <button id="target" class="btn"></button>
                `,
                event: [{ tag_name: 'button', attr_id: 'target', nth_child: 1, nth_of_type: 1 }],
            },
            {
                name: 'ignores drifted sibling position when the clicked element is identified by a data attribute',
                html: `
                    <div class="injected-banner"></div>
                    <button data-attr="cta" id="target"></button>
                `,
                event: [
                    {
                        tag_name: 'button',
                        attributes: { 'attr__data-attr': 'cta' },
                        nth_child: 1,
                        nth_of_type: 1,
                    },
                ],
                dataAttributes: ['data-attr'],
            },
            {
                name: 'ignores drifted sibling position when the ancestor is identified by id',
                html: `
                    <div class="injected-banner"></div>
                    <div id="main-panel"><button class="btn" id="target"></button></div>
                    <div class="other"><button class="btn"></button></div>
                `,
                event: [
                    { tag_name: 'button', attr_class: ['btn'], nth_child: 1, nth_of_type: 1 },
                    { tag_name: 'div', attr_id: 'main-panel', nth_child: 1, nth_of_type: 1 },
                ],
            },
            {
                name: 'ignores drifted sibling position when the ancestor is identified by a data attribute',
                html: `
                    <div class="injected-banner"></div>
                    <div data-attr="main-panel"><button class="btn" id="target"></button></div>
                    <div class="other"><button class="btn"></button></div>
                `,
                event: [
                    { tag_name: 'button', attr_class: ['btn'], nth_child: 1, nth_of_type: 1 },
                    {
                        tag_name: 'div',
                        attributes: { 'attr__data-attr': 'main-panel' },
                        nth_child: 1,
                        nth_of_type: 1,
                    },
                ],
                dataAttributes: ['data-attr'],
            },
        ]

        it.each(parentChainCases)('$name', ({ html, event, dataAttributes = [] }) => {
            const { container, cleanup } = createTestDOM(html)
            try {
                const index = buildDOMIndex(getAllElements(container))
                const result = matchEventToElementUsingIndex(createEvent(event), index, { dataAttributes })

                expect(result).not.toBeNull()
                expect(result?.element.id).toBe('target')
            } finally {
                cleanup()
            }
        })

        const discriminatorCases = [
            {
                name: 'breaks a structural tie using the captured href',
                html: `
                    <nav class="menu">
                        <a class="item" id="decoy" href="/reports"></a>
                        <a class="item" id="target" href="/settings"></a>
                    </nav>
                `,
                event: [
                    { tag_name: 'a', attr_class: ['item'], href: '/settings' },
                    { tag_name: 'nav', attr_class: ['menu'] },
                ],
                expectedId: 'target',
                expectedIdWhenOff: null,
            },
            {
                name: 'breaks a structural tie using the captured text when there is no href',
                html: `
                    <div class="toolbar">
                        <button class="btn" id="decoy">Save</button>
                        <button class="btn" id="target">Delete</button>
                    </div>
                `,
                event: [
                    { tag_name: 'button', attr_class: ['btn'], text: 'Delete' },
                    { tag_name: 'div', attr_class: ['toolbar'] },
                ],
                expectedId: 'target',
                expectedIdWhenOff: null,
            },
            {
                name: 'rejects a lone survivor the chain contradicts and resolves the real element',
                html: `
                    <nav class="group"><a class="item" id="target" href="/reports">Reports</a></nav>
                    <nav class="group expanded"><a class="item" id="decoy" href="/settings">Settings</a></nav>
                `,
                event: [
                    { tag_name: 'a', attr_class: ['item'], href: '/reports', text: 'Reports' },
                    { tag_name: 'nav', attr_class: ['group', 'expanded'] },
                ],
                expectedId: 'target',
                expectedIdWhenOff: 'decoy',
            },
            {
                name: 'returns null rather than attributing to an element the chain contradicts',
                html: `
                    <nav class="group"><a class="item" href="/reports">Reports</a></nav>
                    <nav class="group expanded"><a class="item" id="decoy" href="/settings">Settings</a></nav>
                `,
                event: [
                    { tag_name: 'a', attr_class: ['item'], href: '/archive', text: 'Archive' },
                    { tag_name: 'nav', attr_class: ['group', 'expanded'] },
                ],
                expectedId: null,
                expectedIdWhenOff: 'decoy',
            },
            {
                name: 'narrows by href first, then breaks the remaining tie with the captured text',
                html: `
                    <nav class="menu">
                        <a class="item" id="other" href="/pricing">Getting started</a>
                        <a class="item" id="decoy" href="/docs">API reference</a>
                        <a class="item" id="target" href="/docs">Getting started</a>
                    </nav>
                `,
                event: [
                    { tag_name: 'a', attr_class: ['item'], href: '/docs', text: 'Getting started' },
                    { tag_name: 'nav', attr_class: ['menu'] },
                ],
                expectedId: 'target',
                expectedIdWhenOff: null,
            },
            {
                name: 'still matches when captured text is truncated relative to the live DOM',
                html: `
                    <div class="toolbar">
                        <button class="btn" id="decoy">Discard all unsaved changes</button>
                        <button class="btn" id="target">Publish every pending revision</button>
                    </div>
                `,
                event: [
                    { tag_name: 'button', attr_class: ['btn'], text: 'Publish every' },
                    { tag_name: 'div', attr_class: ['toolbar'] },
                ],
                expectedId: 'target',
                expectedIdWhenOff: null,
            },
        ]

        it.each(
            discriminatorCases.flatMap(({ expectedId, expectedIdWhenOff, ...rest }) => [
                { ...rest, useDiscriminators: true, expected: expectedId },
                { ...rest, useDiscriminators: false, expected: expectedIdWhenOff },
            ])
        )('$name (useDiscriminators=$useDiscriminators)', ({ html, event, useDiscriminators, expected }) => {
            const { container, cleanup } = createTestDOM(html)
            try {
                const index = buildDOMIndex(getAllElements(container))
                const result = matchEventToElementUsingIndex(createEvent(event), index, { useDiscriminators })

                expect(result?.element.id ?? null).toBe(expected)
            } finally {
                cleanup()
            }
        })

        it('applies isTooSimple check for generic elements', () => {
            const { container, cleanup } = createTestDOM('<div><div></div></div>')
            try {
                const index = buildDOMIndex(getAllElements(container))
                const event = createEvent([{ tag_name: 'div', nth_child: 1, nth_of_type: 1 }])
                const result = matchEventToElementUsingIndex(event, index)

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
                const result = matchEventToElementUsingIndex(event, index)

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
                const result = matchEventToElementUsingIndex(event, index)

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
                const result = matchEventToElementUsingIndex(event, index)

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
            {
                name: 'matches within repeated identical structures via ancestor position',
                html: `
                    <div class="row"><a class="link" href="/one">One</a></div>
                    <div class="row"><a class="link" href="/two">Two</a></div>
                    <div class="row"><a class="link" href="/three">Three</a></div>
                `,
                event: [
                    { tag_name: 'a', attr_class: ['link'], nth_child: 1, nth_of_type: 1 },
                    { tag_name: 'div', attr_class: ['row'], nth_child: 3, nth_of_type: 3 },
                ],
            },
            {
                name: 'matches when only a grandparent disambiguates',
                html: `
                    <section class="outer-a"><div class="middle"><button class="btn">A</button></div></section>
                    <section class="outer-b"><div class="middle"><button class="btn">B</button></div></section>
                `,
                event: [
                    { tag_name: 'button', attr_class: ['btn'] },
                    { tag_name: 'div', attr_class: ['middle'] },
                    { tag_name: 'section', attr_class: ['outer-b'] },
                ],
            },
        ]

        const shadowRootModes = [{ hasShadowRoots: true }, { hasShadowRoots: false }]

        it.each(comparisonCases.flatMap((c) => shadowRootModes.map((mode) => ({ ...c, ...mode }))))(
            '$name: both implementations agree (hasShadowRoots=$hasShadowRoots)',
            ({ html, event, dataAttributes = [], hasShadowRoots }) => {
                const { cleanup } = createTestDOM(html)
                try {
                    const pageElements = collectAllElementsDeep('*', document) as HTMLElement[]
                    const index = buildDOMIndex(pageElements)
                    const selectorCache = new Map<string, HTMLElement[]>()

                    const eventObj = createEvent(event)

                    const indexResult = matchEventToElementUsingIndex(eventObj, index, {
                        dataAttributes,
                        matchLinksByHref: true,
                    })
                    const selectorResult = matchEventToElementUsingSelectors(
                        eventObj,
                        dataAttributes,
                        true,
                        pageElements,
                        selectorCache,
                        hasShadowRoots
                    )

                    if (selectorResult === null) {
                        expect(indexResult).toBeNull()
                    } else {
                        expect(indexResult).not.toBeNull()
                        expect(indexResult?.element).toBe(selectorResult.element)
                        expect(indexResult?.count).toBe(selectorResult.count)
                        expect(indexResult?.hash).toBe(selectorResult.hash)
                    }
                } finally {
                    cleanup()
                }
            }
        )
    })

    describe('matchIsChainConsistent', () => {
        const consistencyCases = [
            {
                name: 'accepts an element whose whole ancestor path matches the chain',
                html: '<nav class="group"><a class="item" id="target" href="/reports">Reports</a></nav>',
                selector: '#target',
                chain: [
                    { tag_name: 'a', attr_id: 'target', nth_child: 1, nth_of_type: 1 },
                    { tag_name: 'nav', nth_child: 1, nth_of_type: 1 },
                ],
                expected: true,
            },
            {
                name: 'rejects an element sitting at a different ancestor position',
                html: `
                    <div><nav class="group"><a class="item" href="/reports"></a></nav>
                    <nav class="group"><a class="item" id="decoy" href="/settings"></a></nav></div>
                `,
                selector: '#decoy',
                chain: [
                    { tag_name: 'a', nth_child: 1, nth_of_type: 1 },
                    { tag_name: 'nav', nth_child: 1, nth_of_type: 1 },
                ],
                expected: false,
            },
            {
                name: 'ignores classes so legitimate class drift is not counted as misattribution',
                html: '<nav class="group expanded ng-star-inserted"><a class="item extra" id="target"></a></nav>',
                selector: '#target',
                chain: [
                    { tag_name: 'a', nth_child: 1, nth_of_type: 1 },
                    { tag_name: 'nav', nth_child: 1, nth_of_type: 1 },
                ],
                expected: true,
            },
            {
                name: 'rejects a chain deeper than the live ancestor path',
                html: '<nav><a id="target"></a></nav>',
                selector: '#target',
                chain: [
                    { tag_name: 'a' },
                    { tag_name: 'nav' },
                    { tag_name: 'section' },
                    { tag_name: 'main' },
                    { tag_name: 'div' },
                    { tag_name: 'div' },
                ],
                expected: false,
            },
            {
                name: 'ignores href and text so the measure stays independent of how the match was chosen',
                html: '<nav><a id="target" href="/actual">Actual</a></nav>',
                selector: '#target',
                chain: [
                    { tag_name: 'a', href: '/different', text: 'Different', nth_child: 1, nth_of_type: 1 },
                    { tag_name: 'nav', nth_child: 1, nth_of_type: 1 },
                ],
                expected: true,
            },
        ]

        it.each(consistencyCases)('$name', ({ html, selector, chain, expected }) => {
            const { container, cleanup } = createTestDOM(html)
            try {
                const element = container.querySelector<HTMLElement>(selector)!
                const elements = chain.map((level) => ({ attributes: {}, ...level })) as ElementType[]
                const index = buildDOMIndex(getAllElements(container))

                expect(matchIsChainConsistent(element, elements, index)).toBe(expected)
            } finally {
                cleanup()
            }
        })
    })
})
