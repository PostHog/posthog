import { CHROME_EXTENSION_DENY_LIST, stripChromeExtensionDataFromNode } from './chrome-extension-stripping'

describe('stripChromeExtensionDataFromNode', () => {
    const needles = Object.keys(CHROME_EXTENSION_DENY_LIST)

    it('does not throw when node.attributes is explicitly undefined', () => {
        const node = {
            type: 2,
            id: 1,
            tagName: 'div',
            attributes: undefined,
            childNodes: [],
        } as any
        const matchedExtensions = new Set<string>()

        expect(() => stripChromeExtensionDataFromNode(node, needles, matchedExtensions)).not.toThrow()
        expect(matchedExtensions.size).toBe(0)
    })

    it('does not throw when node.attributes is null', () => {
        const node = {
            type: 2,
            id: 1,
            tagName: 'div',
            attributes: null,
            childNodes: [],
        } as any
        const matchedExtensions = new Set<string>()

        expect(() => stripChromeExtensionDataFromNode(node, needles, matchedExtensions)).not.toThrow()
        expect(matchedExtensions.size).toBe(0)
    })

    it('does not throw when a child node has undefined attributes', () => {
        const node = {
            type: 2,
            id: 1,
            tagName: 'html',
            attributes: {},
            childNodes: [
                {
                    type: 2,
                    id: 2,
                    tagName: 'div',
                    attributes: undefined,
                    childNodes: [],
                },
            ],
        } as any
        const matchedExtensions = new Set<string>()

        expect(() => stripChromeExtensionDataFromNode(node, needles, matchedExtensions)).not.toThrow()
    })

    it('still strips class attribute matches on well-formed nodes', () => {
        const node = {
            type: 2,
            id: 1,
            tagName: 'DIV',
            attributes: { class: 'wrapper aitopia-widget' },
            childNodes: [{ id: 2, type: 3, textContent: 'secret' }],
        } as any
        const matchedExtensions = new Set<string>()

        const stripped = stripChromeExtensionDataFromNode(node, needles, matchedExtensions)
        expect(stripped).toBe(true)
        expect(matchedExtensions.has('aitopia')).toBe(true)
        expect(node.attributes.class).not.toContain('aitopia')
    })

    it('still strips id-based matches on well-formed nodes', () => {
        const node = {
            type: 2,
            id: 1,
            tagName: 'div',
            attributes: { id: 'sublime-root' },
            childNodes: [{ id: 2, type: 3, textContent: 'secret' }],
        } as any
        const matchedExtensions = new Set<string>()

        const stripped = stripChromeExtensionDataFromNode(node, needles, matchedExtensions)
        expect(stripped).toBe(true)
        expect(node.childNodes).toEqual([])
        expect(matchedExtensions.has('sublime pop-up')).toBe(true)
    })

    it('does not throw when _cssText attribute exists but attributes is undefined', () => {
        const node = {
            type: 2,
            id: 1,
            tagName: 'style',
            attributes: undefined,
            childNodes: [],
        } as any
        const matchedExtensions = new Set<string>()

        expect(() => stripChromeExtensionDataFromNode(node, needles, matchedExtensions)).not.toThrow()
    })
})
