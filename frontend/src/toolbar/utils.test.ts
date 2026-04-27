import {
    buildFallbackSelector,
    elementAncestorDepth,
    elementToQuery,
    joinWithUiHost,
    slashDotDataAttrUnescape,
} from './utils'

describe('utils', () => {
    describe('elementAncestorDepth', () => {
        it('returns 0 for an element without a parent', () => {
            const orphan = document.createElement('div')
            expect(elementAncestorDepth(orphan)).toBe(0)
        })

        it('counts ancestors up to the document root', () => {
            const grandparent = document.createElement('div')
            const parent = document.createElement('div')
            const child = document.createElement('span')
            grandparent.appendChild(parent)
            parent.appendChild(child)
            document.body.appendChild(grandparent)

            // 4 ancestors: parent, grandparent, body, html
            expect(elementAncestorDepth(child)).toBe(4)

            grandparent.remove()
        })

        it('stops counting once the limit is exceeded', () => {
            let current = document.createElement('div')
            const root = current
            for (let i = 0; i < 100; i++) {
                const next = document.createElement('div')
                current.appendChild(next)
                current = next
            }
            document.body.appendChild(root)

            // limit=10 means we stop walking after we've gone 11 steps up
            expect(elementAncestorDepth(current, 10)).toBeLessThanOrEqual(12)

            root.remove()
        })
    })

    describe('buildFallbackSelector', () => {
        it('prefers id when present', () => {
            const el = document.createElement('div')
            el.id = 'foo'
            expect(buildFallbackSelector(el)).toBe('[id="foo"]')
        })

        it('uses a data-* attribute when no id is set', () => {
            const el = document.createElement('div')
            el.setAttribute('data-test', 'bar')
            expect(buildFallbackSelector(el)).toBe('[data-test="bar"]')
        })

        it('falls back to tag + classes when no id or data-* attribute', () => {
            const el = document.createElement('span')
            el.classList.add('alpha', 'beta', 'gamma')
            expect(buildFallbackSelector(el)).toBe('span.alpha.beta')
        })

        it('falls back to bare tag name when no other identifiers exist', () => {
            const el = document.createElement('section')
            expect(buildFallbackSelector(el)).toBe('section')
        })
    })

    describe('elementToQuery (deeply nested DOM)', () => {
        it('returns a fallback selector instead of recursing into finder() on deeply nested elements', () => {
            // Build a chain deeper than MAX_NESTED_DEPTH_FOR_FINDER (50)
            let current = document.createElement('div')
            const root = current
            for (let i = 0; i < 80; i++) {
                const next = document.createElement('div')
                current.appendChild(next)
                current = next
            }
            current.id = 'deeply-nested-leaf'
            document.body.appendChild(root)

            // No exception should be thrown; we should get the fallback selector
            const result = elementToQuery(current, [])
            expect(result).toBe('[id="deeply-nested-leaf"]')

            root.remove()
        })
    })

    describe('joinWithUiHost', () => {
        const testCases: Array<{ uiHost: string; path: string; expected: string }> = [
            {
                uiHost: 'https://us.posthog.com',
                path: '/settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com/',
                path: '/settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com///',
                path: 'settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com',
                path: 'settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com/',
                path: '///settings/project',
                expected: 'https://us.posthog.com/settings/project',
            },
            {
                uiHost: 'https://us.posthog.com',
                path: `${'/settings/project'}#heatmaps`,
                expected: 'https://us.posthog.com/settings/project#heatmaps',
            },
            { uiHost: 'https://us.posthog.com', path: '?a=1', expected: 'https://us.posthog.com/?a=1' },
            { uiHost: 'https://us.posthog.com', path: '#hash', expected: 'https://us.posthog.com/#hash' },
            { uiHost: 'https://us.posthog.com', path: 'https://example.com/x', expected: 'https://example.com/x' },
            { uiHost: 'https://us.posthog.com', path: '//example.com/x', expected: '//example.com/x' },
            { uiHost: '', path: '/settings/project', expected: '/settings/project' },
        ]

        testCases.forEach(({ uiHost, path, expected }) => {
            it(`joins "${uiHost}" + "${path}"`, () => {
                expect(joinWithUiHost(uiHost, path)).toBe(expected)
            })
        })
    })

    describe('slashDotDataAttrUnescape', () => {
        const testCases = [
            {
                input: 'div[data-attr="test"]',
                expected: 'div[data-attr="test"]',
            },
            {
                input: 'div[data-attr="test\\."]',
                expected: 'div[data-attr="test."]',
            },
            {
                input: 'div[data-something="test\\.test\\.test"]',
                expected: 'div[data-something="test.test.test"]',
            },
            {
                input: '.tomato div[data-something="test\\.test\\.test"]',
                expected: '.tomato div[data-something="test.test.test"]',
            },
            {
                input: '\\.tomato div[data-something="test\\.test\\.test"]',
                expected: '.tomato div[data-something="test.test.test"]',
            },
        ]
        testCases.forEach(({ input, expected }) => {
            it(`should unescape "${input}" to "${expected}"`, () => {
                const result = slashDotDataAttrUnescape(input)
                expect(result).toBe(expected)
            })
        })
    })
})
