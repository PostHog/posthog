import { NodeType, serializedNodeWithId } from '@posthog/rrweb-types'

import { CHROME_EXTENSION_DENY_LIST, stripChromeExtensionDataFromNode } from './chrome-extension-stripping'

describe('stripChromeExtensionDataFromNode', () => {
    const needles = Object.keys(CHROME_EXTENSION_DENY_LIST)

    it.each([
        ['attributes is undefined', undefined],
        ['attributes is null', null],
    ])('does not throw when %s', (_label, attributes) => {
        const node = {
            type: NodeType.Element,
            tagName: 'div',
            attributes,
            childNodes: [],
            id: 1,
        } as unknown as serializedNodeWithId

        const matched = new Set<string>()
        expect(() => stripChromeExtensionDataFromNode(node, needles, matched)).not.toThrow()
        expect(matched.size).toBe(0)
    })

    it('does not throw or match when attributes object lacks relevant keys', () => {
        const node: serializedNodeWithId = {
            type: NodeType.Element,
            tagName: 'div',
            attributes: { 'data-safe': 'yes' },
            childNodes: [],
            id: 1,
        }

        const matched = new Set<string>()
        expect(stripChromeExtensionDataFromNode(node, needles, matched)).toBe(false)
        expect(matched.size).toBe(0)
    })

    it('strips children when id attribute matches a needle', () => {
        const node: serializedNodeWithId = {
            type: NodeType.Element,
            tagName: 'div',
            attributes: { id: 'dji-sru-root' },
            childNodes: [
                {
                    type: NodeType.Text,
                    textContent: 'sensitive',
                    id: 2,
                },
            ],
            id: 1,
        }

        const matched = new Set<string>()
        expect(stripChromeExtensionDataFromNode(node, needles, matched)).toBe(true)
        expect((node as { childNodes: serializedNodeWithId[] }).childNodes).toEqual([])
        expect(matched.has('snap and read')).toBe(true)
    })

    it('removes the needle from a matching class attribute on a DIV', () => {
        const node: serializedNodeWithId = {
            type: NodeType.Element,
            tagName: 'DIV',
            attributes: { class: 'wrapper aitopia inner' },
            childNodes: [],
            id: 1,
        }

        const matched = new Set<string>()
        expect(stripChromeExtensionDataFromNode(node, needles, matched)).toBe(true)
        expect((node as { attributes: Record<string, string> }).attributes.class).not.toContain('aitopia')
        expect(matched.has('aitopia')).toBe(true)
    })

    it('strips children when tagName includes a needle', () => {
        const node: serializedNodeWithId = {
            type: NodeType.Element,
            tagName: 'sublime-root-widget',
            attributes: {},
            childNodes: [
                {
                    type: NodeType.Text,
                    textContent: 'overlay',
                    id: 2,
                },
            ],
            id: 1,
        }

        const matched = new Set<string>()
        expect(stripChromeExtensionDataFromNode(node, needles, matched)).toBe(true)
        expect((node as { childNodes: serializedNodeWithId[] }).childNodes).toEqual([])
        expect(matched.has('sublime pop-up')).toBe(true)
    })

    it('recurses into children and strips nested matches', () => {
        const node: serializedNodeWithId = {
            type: NodeType.Element,
            tagName: 'body',
            attributes: {},
            childNodes: [
                {
                    type: NodeType.Element,
                    tagName: 'DIV',
                    attributes: { class: 'aitopia' },
                    childNodes: [
                        {
                            type: NodeType.Text,
                            textContent: 'ad',
                            id: 3,
                        },
                    ],
                    id: 2,
                },
            ],
            id: 1,
        }

        const matched = new Set<string>()
        expect(stripChromeExtensionDataFromNode(node, needles, matched)).toBe(true)
        expect(matched.has('aitopia')).toBe(true)
    })

    it('does not throw when a nested child has undefined attributes', () => {
        const node = {
            type: NodeType.Element,
            tagName: 'body',
            attributes: {},
            childNodes: [
                {
                    type: NodeType.Element,
                    tagName: 'div',
                    attributes: undefined,
                    childNodes: [],
                    id: 2,
                },
            ],
            id: 1,
        } as unknown as serializedNodeWithId

        const matched = new Set<string>()
        expect(() => stripChromeExtensionDataFromNode(node, needles, matched)).not.toThrow()
        expect(matched.size).toBe(0)
    })
})
