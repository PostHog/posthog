import { ElementType } from '~/types'
import { parseCSSSelector, matchesSelector, preselect } from 'lib/components/HTMLElementsDisplay/preselectWithCSS'
import { expect } from '../../../../../playwright/fixtures/storybook'

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
    describe('can parse parts out of a single selector', () => {
        test('can grab a tag from a simple tag only selector', () => {
            expect(parseCSSSelector('div')).toEqual({ tag: 'div' })
        })
        test('can grab a class from a simple class only selector', () => {
            expect(parseCSSSelector('.Something__something--something')).toEqual({
                class: 'Something__something--something',
            })
        })
        test('can grab an attribute from a simple attribute only selector', () => {
            expect(parseCSSSelector('[key="value"]')).toEqual({
                key: 'value',
            })
        })
        test('can ignore pseudo-selectors', () => {
            expect(parseCSSSelector('.Something__something--something:first-of-type')).toEqual({
                class: 'Something__something--something',
            })
        })
        test('can grab multiple from a complex selector', () => {
            expect(
                parseCSSSelector('span.Something__something--something:first-of-type[href="wat"].second-class')
            ).toEqual({
                class: ['Something__something--something', 'second-class'],
                href: 'wat',
                tag: 'span',
            })
        })
        test('treats # as an id attr', () => {
            expect(parseCSSSelector('div#wat')).toEqual({
                id: 'wat',
                tag: 'div',
            })
        })

        test('can handle direct child combinators', () => {
            expect(parseCSSSelector('>')).toEqual({
                combinator: '>',
            })
        })

        test('can ignore adjacent sibling combinators', () => {
            expect(parseCSSSelector('+')).toEqual({})
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
                class: 'SideBar--hidden',
            },
        })
    })

    test('no child combinator', () => {
        const autoSelector = '.top-list-container-horizontal .top-list:nth-child(1) .LemonButton:nth-child(1)'

        const expectedSelectedElements = {
            4: {
                class: 'top-list-container-horizontal',
            },
            5: {
                class: 'top-list',
            },
            8: {
                class: 'LemonButton',
            },
        }

        expect(preselect(elements, autoSelector)).toEqual(expectedSelectedElements)
    })

    test('multiple css matches on single elements', () => {
        const autoSelector =
            '.top-list-container-horizontal .top-list:nth-child(1) .LemonButton.LemonButton--status-primary:nth-child(1)'

        const expectedSelectedElements = {
            4: {
                class: 'top-list-container-horizontal',
            },
            5: {
                class: 'top-list',
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
                class: 'top-list-container-horizontal',
            },
            5: {
                class: 'top-list',
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
                class: 'parent',
            },
            4: {
                tag: 'div',
                class: 'child',
            },
            5: {
                tag: 'div',
                class: 'grandchild',
            },
        })
    })
})
