import { EXAMPLE_ELEMENTS } from 'lib/components/HTMLElementsDisplay/HTMLElementsDisplay.stories'
import { elementsChain } from 'lib/components/HTMLElementsDisplay/htmlElementsDisplayLogic'
import {
    matchesSelector,
    parseCSSSelector,
    parsedSelectorToSelectorString,
    preselect,
} from 'lib/components/HTMLElementsDisplay/preselectWithCSS'

import { ElementType } from '~/types'

const elements = [
    {
        attributes: {},
        tag_name: 'div',
    },
    {
        attributes: {
            class: 'SideBar SideBar__layout SideBar--hidden',
        },
        tag_name: 'div',
    },
    {
        attributes: {
            class: 'main-app-content',
        },
        tag_name: 'div',
    },
    {
        attributes: {
            class: 'project-homepage',
        },
        tag_name: 'div',
    },
    {
        attributes: {
            class: 'top-list-container-horizontal',
        },
        tag_name: 'div',
    },
    {
        attributes: {
            class: 'top-list',
        },
        tag_name: 'div',
    },
    {
        attributes: {
            class: 'compact-list',
        },
        tag_name: 'div',
    },
    {
        attributes: {
            class: 'scrollable-list',
        },
        tag_name: 'div',
    },
    {
        attributes: {
            type: 'button',
            class: 'LemonButton LemonButton--tertiary LemonButton--status-primary LemonButton--full-width',
            href: '/insights/0UJGO3yI',
        },
        href: '/insights/0UJGO3yI',
        tag_name: 'a',
        text: 'Pageview count\nLast modified 2 days ago',
    },
] as ElementType[]
describe('can preselect selectors for editing', () => {
    describe('can parse parts out of a single selector and they are mostly reversible', () => {
        const testcases = [
            { selector: 'div', expected: { tag: 'div' } },
            { selector: '.Something__something--something', expected: { class: ['Something__something--something'] } },
            {
                selector: '.Something__something--something:first-of-type',
                expectedSelector: '.Something__something--something',
                expected: { class: ['Something__something--something'] },
            },
            { selector: '[key="value"]', expected: { key: 'value' } },
            {
                selector: 'span.Something__something--something:first-of-type[href="wat"].second-class',
                expectedSelector: 'span.Something__something--something.second-class[href="wat"]',
                expected: {
                    class: ['Something__something--something', 'second-class'],
                    href: 'wat',
                    tag: 'span',
                },
            },
            {
                selector: 'div#wat',
                expectedSelector: 'div[id="wat"]',
                expected: {
                    id: 'wat',
                    tag: 'div',
                },
            },
            {
                selector: '>',
                expected: {
                    combinator: '>',
                },
            },
            {
                selector: '+',
                expectedSelector: '',
                expected: {},
            },
        ]

        testcases.forEach((testcase) => {
            test(`can parse ${testcase.selector}`, () => {
                expect(parseCSSSelector(testcase.selector)).toEqual(testcase.expected)
                expect(parsedSelectorToSelectorString(testcase.expected)).toEqual(
                    // some selectors are not reversible since we throw away some information
                    testcase.expectedSelector === undefined ? testcase.selector : testcase.expectedSelector
                )
            })
        })
    })

    describe('elements can be matched to ParsedCSSSelectors', () => {
        test('a simple tag match', () => {
            const el = {
                tag_name: 'div',
                attributes: {},
            } as ElementType
            const selector = parseCSSSelector('div')
            expect(matchesSelector(el, selector)).toBe(true)
        })
        test('a simple tag miss', () => {
            const el = {
                tag_name: 'div',
                attributes: {},
            } as ElementType
            const selector = parseCSSSelector('span')
            expect(matchesSelector(el, selector)).toBe(false)
        })

        test('a simple class match', () => {
            const el = {
                tag_name: 'span',
                attributes: {
                    class: 'something',
                },
            } as ElementType
            const selector = parseCSSSelector('.something')
            expect(matchesSelector(el, selector)).toBe(true)
        })

        test('a simple class match with attr__ prefix', () => {
            const el = {
                tag_name: 'span',
                attributes: {
                    attr__class: 'something',
                },
            } as ElementType
            const selector = parseCSSSelector('.something')
            expect(matchesSelector(el, selector)).toBe(true)
        })

        test('a simple class miss', () => {
            const el = {
                tag_name: 'span',
            } as ElementType
            const selector = parseCSSSelector('span.something')
            expect(matchesSelector(el, selector)).toBe(false)
        })

        test('a simple hash id match', () => {
            const el = {
                tag_name: 'span',
                attributes: {
                    id: 'something',
                },
            } as ElementType
            const selector = parseCSSSelector('#something')
            expect(matchesSelector(el, selector)).toBe(true)
        })

        test('a simple attribute id match', () => {
            const el = {
                tag_name: 'span',
                attributes: {
                    id: 'something',
                },
            } as ElementType
            const selector = parseCSSSelector('[id="something"]')
            expect(matchesSelector(el, selector)).toBe(true)
        })

        test('a simple attribute match', () => {
            const el = {
                tag_name: 'a',
                attributes: {
                    href: 'something',
                },
            } as ElementType
            const selector = parseCSSSelector('[href="something"]')
            expect(matchesSelector(el, selector)).toBe(true)
        })

        test('rejects combinators', () => {
            const el = {
                tag_name: 'a',
                attributes: {
                    href: 'something',
                },
            } as ElementType
            const selector = parseCSSSelector('>')
            expect(matchesSelector(el, selector)).toBe(false)
        })
    })

    test('a single tag can be selected', () => {
        const elements = [
            {
                attributes: {},
                tag_name: 'div',
            },
        ] as ElementType[]

        const autoSelector = 'div'

        const expectedSelectedElements = {
            0: {
                tag: 'div',
            },
        }

        expect(preselect(elements, autoSelector)).toEqual(expectedSelectedElements)
    })

    test('no matches returns empty', () => {
        const elements = [
            {
                attributes: {},
                tag_name: 'div',
            },
        ] as ElementType[]

        const autoSelector = 'span'

        expect(preselect(elements, autoSelector)).toEqual({})
    })

    test('can match tag and class', () => {
        const elements = [
            {
                attr_class: 'SideBar SideBar__layout SideBar--hidden',
                attributes: {
                    class: 'SideBar SideBar__layout SideBar--hidden',
                },
                tag_name: 'div',
            } as unknown as ElementType,
        ] as ElementType[]

        const autoSelector = 'div.SideBar--hidden'

        expect(preselect(elements, autoSelector)).toEqual({
            0: {
                tag: 'div',
                class: ['SideBar--hidden'],
            },
        })
    })

    test('no child combinator', () => {
        const autoSelector = '.top-list-container-horizontal .top-list:nth-child(1) .LemonButton:nth-child(1)'

        const expectedSelectedElements = {
            4: {
                class: ['top-list-container-horizontal'],
            },
            5: {
                class: ['top-list'],
            },
            8: {
                class: ['LemonButton'],
            },
        }

        expect(preselect(elements, autoSelector)).toEqual(expectedSelectedElements)
    })

    test('multiple css matches on single elements', () => {
        const autoSelector =
            '.top-list-container-horizontal .top-list:nth-child(1) .LemonButton.LemonButton--status-primary:nth-child(1)'

        const expectedSelectedElements = {
            4: {
                class: ['top-list-container-horizontal'],
            },
            5: {
                class: ['top-list'],
            },
            8: {
                class: ['LemonButton', 'LemonButton--status-primary'],
            },
        }

        expect(preselect(elements, autoSelector)).toEqual(expectedSelectedElements)
    })

    test('multiple types of css matches', () => {
        const autoSelector =
            '.top-list-container-horizontal .top-list:nth-child(1) .LemonButton.LemonButton--status-primary[href="/insights/0UJGO3yI"]'

        const expectedSelectedElements = {
            4: {
                class: ['top-list-container-horizontal'],
            },
            5: {
                class: ['top-list'],
            },
            8: {
                class: ['LemonButton', 'LemonButton--status-primary'],
                href: '/insights/0UJGO3yI',
            },
        }

        expect(preselect(elements, autoSelector)).toEqual(expectedSelectedElements)
    })

    test('when child combinator is necessary', () => {
        const selector = 'div.parent div.child > div.grandchild'
        // the below will match parent and child at index 1 and 2 naively but,
        // because of the child combinator, it should only match the parent
        // at either 1 or 3
        // and then the child and grandchild at 4, and 5
        const elements = [
            {
                attributes: {},
                tag_name: 'div',
            },
            {
                attributes: {
                    class: 'parent',
                },
                tag_name: 'div',
            },
            {
                attributes: {
                    class: 'child',
                },
                tag_name: 'div',
            },
            {
                attributes: {
                    class: 'parent',
                },
                tag_name: 'div',
            },
            {
                attributes: {
                    class: 'child',
                },
                tag_name: 'div',
            },
            {
                attributes: {
                    class: 'grandchild',
                },
                tag_name: 'div',
            },
        ] as ElementType[]
        expect(preselect(elements, selector)).toEqual({
            1: {
                tag: 'div',
                class: ['parent'],
            },
            4: {
                tag: 'div',
                class: ['child'],
            },
            5: {
                tag: 'div',
                class: ['grandchild'],
            },
        })
    })

    test('fixing the storybook example', () => {
        const selector = 'div div.SideBar .LemonButton__content span.text-default'

        expect(preselect(elementsChain(EXAMPLE_ELEMENTS), selector)).toEqual({
            '1': {
                tag: 'div',
            },
            '3': {
                class: ['SideBar'],
                tag: 'div',
            },
            '10': {
                class: ['LemonButton__content'],
            },
            '11': {
                class: ['text-default'],
                tag: 'span',
            },
        })
    })

    /**
     * regression test for the case where if all selectors match the pre-selector will run for eternity
     * see: https://posthoghelp.zendesk.com/agent/tickets/2945
     * */
    test('it does not run for eternity when all selectors match', () => {
        const selector =
            '.search-box__result-item:nth-child(1) .example-l-flex__item:nth-child(1) > .example-c-button-group .example-c-button'

        expect(
            preselect(
                [
                    {
                        attributes: {
                            class: 'example-o-stack__item',
                        },
                        tag_name: 'div',
                    },
                    {
                        attributes: {
                            class: 'search-box__result-item',
                        },
                        tag_name: 'div',
                    },
                    {
                        attributes: {
                            'data-testid': 'searchResultItem',
                        },
                        tag_name: 'div',
                    },
                    {
                        attributes: {
                            class: 'example-l-flex__item example-l-flex example-l-flex--gutter-none example-l-flex--direction-column@s-up example-l-flex--align-items-stretch@s-up example-l-flex--justify-content-flex-start@s-up example-l-flex--wrap-nowrap@s-up search-journal-item',
                        },
                        tag_name: 'div',
                    },
                    {
                        attributes: {
                            class: 'example-l-flex__item search-journal-item__social-bar',
                        },
                        tag_name: 'div',
                    },
                    {
                        attributes: {
                            class: 'example-l-flex__item example-l-flex example-l-flex--gutter-m example-l-flex--direction-row@s-up example-l-flex--align-items-center@s-up example-l-flex--justify-content-flex-start@s-up example-l-flex--wrap-wrap@s-up',
                        },
                        tag_name: 'div',
                    },
                    {
                        attributes: {
                            class: 'example-l-flex__item example-l-flex__item--grow',
                        },
                        tag_name: 'div',
                    },
                    {
                        attributes: {
                            class: 'example-c-button-group example-c-button-group--gutter-m example-c-button-group--orientation-horizontal example-c-button-group--width-auto',
                        },
                        tag_name: 'div',
                    },
                    {
                        attributes: {
                            class: 'example-c-button-group__item',
                        },
                        tag_name: 'div',
                    },
                    {
                        attributes: {
                            class: 'example-c-button example-c-button--align-center example-c-button--radius-full example-c-button--size-s example-c-button--color-blue example-c-button--theme-ghost',
                        },
                        tag_name: 'a',
                        text: 'View',
                    },
                ],
                selector
            )
        ).toEqual({
            '1': {
                class: ['search-box__result-item'],
            },
            '6': {
                class: ['example-l-flex__item'],
            },
            '7': {
                class: ['example-c-button-group'],
            },
            '8': {
                class: ['example-c-button'],
            },
        })
    })
})
