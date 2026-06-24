import { defaultAllowLists } from './default-dict'
import { scrubFullSnapshot, scrubMutation } from './dom'

describe('anonymize/dom', () => {
    const ctx = { allow: defaultAllowLists(), maxWordsLen: 8 }

    it('scrubs text nodes but leaves script source untouched', () => {
        const event = {
            type: 2,
            timestamp: 1,
            data: {
                node: {
                    type: 0,
                    id: 1,
                    childNodes: [
                        {
                            type: 2,
                            id: 2,
                            tagName: 'div',
                            attributes: {},
                            childNodes: [{ type: 3, id: 3, textContent: 'Hello SecretName' }],
                        },
                        {
                            type: 2,
                            id: 4,
                            tagName: 'script',
                            attributes: {},
                            childNodes: [{ type: 3, id: 5, textContent: 'var x = 1;' }],
                        },
                    ],
                },
                initialOffset: { top: 0, left: 0 },
            },
        }
        const changed = scrubFullSnapshot(ctx, event.data)
        expect(changed).toBe(true)

        const root = event.data.node
        const div = root.childNodes[0]
        const txt = div.childNodes[0]
        // "Hello" is allow-listed; "SecretName" is 10 chars → ten *s.
        expect(txt.textContent).toBe('Hello **********')

        const script = root.childNodes[1]
        const scriptTxt = script.childNodes[0]
        expect(scriptTxt.textContent).toBe('var x = 1;')
    })

    it('URL-scrubs url attributes and leaves class untouched', () => {
        const event = {
            type: 2,
            timestamp: 1,
            data: {
                node: {
                    type: 0,
                    id: 1,
                    childNodes: [
                        {
                            type: 2,
                            id: 2,
                            tagName: 'a',
                            attributes: { href: 'https://example.com/user/abc/edit', class: 'link primary' },
                            childNodes: [],
                        },
                    ],
                },
                initialOffset: { top: 0, left: 0 },
            },
        }
        scrubFullSnapshot(ctx, event.data)
        const a = event.data.node.childNodes[0]
        expect(a.attributes.href).toBe('https://example.com/user/[redacted]/edit')
        expect(a.attributes.class).toBe('link primary')
    })

    it('preserves non-string attribute values and scrubs only string url/text attrs', () => {
        const event = {
            type: 2,
            timestamp: 1,
            data: {
                node: {
                    type: 0,
                    id: 1,
                    childNodes: [
                        {
                            type: 2,
                            id: 2,
                            tagName: 'body',
                            attributes: {
                                href: 'https://example.com/user/abc/edit',
                                title: 'Smithson lives nearby',
                                class: 'x',
                                'data-n': 3,
                                disabled: true,
                                removed: null,
                            },
                            childNodes: [],
                        },
                    ],
                },
                initialOffset: { top: 0, left: 0 },
            },
        }
        scrubFullSnapshot(ctx, event.data)
        const attrs = event.data.node.childNodes[0].attributes
        // String url/user-text attrs scrubbed:
        expect(attrs.href).toBe('https://example.com/user/[redacted]/edit')
        expect(attrs.title).toBe('******** ***** ******')
        // Non-url/text string left as-is; non-string values untouched:
        expect(attrs.class).toBe('x')
        expect(attrs['data-n']).toBe(3)
        expect(attrs.disabled).toBe(true)
        expect(attrs.removed).toBeNull()
    })

    it('scrubs an inline (uncompressed) mutation', () => {
        const data: any = {
            source: 0,
            texts: [{ id: 5, value: 'Hello SecretName' }],
            attributes: [{ id: 4, attributes: { title: 'Smithson lives nearby', class: 'y' } }],
            removes: [{ parentId: 3, id: 7 }],
            adds: [{ parentId: 4, nextId: null, node: { type: 3, id: 8, textContent: 'Hello Smithson' } }],
        }
        const changed = scrubMutation(ctx, data)
        expect(changed).toBe(true)
        expect(data.texts[0].value).toBe('Hello **********')
        expect(data.attributes[0].attributes.title).toBe('******** ***** ******')
        expect(data.attributes[0].attributes.class).toBe('y')
        expect(data.adds[0].node.textContent).toBe('Hello ********')
        // removes is ids-only and untouched.
        expect(data.removes[0].id).toBe(7)
    })

    it('scrubs Comment and CDATA text content', () => {
        const event = {
            type: 2,
            timestamp: 1,
            data: {
                node: {
                    type: 0,
                    id: 1,
                    childNodes: [
                        { type: 5, id: 2, textContent: 'Hello SecretName' },
                        { type: 4, id: 3, textContent: 'Hello SecretName' },
                        // DocumentType (type 1) carries no text and is left alone.
                        { type: 1, id: 4, name: 'html' },
                    ],
                },
                initialOffset: { top: 0, left: 0 },
            },
        }
        const changed = scrubFullSnapshot(ctx, event.data)
        expect(changed).toBe(true)
        expect(event.data.node.childNodes[0].textContent).toBe('Hello **********')
        expect(event.data.node.childNodes[1].textContent).toBe('Hello **********')
    })

    it('replaces a remote image src with the placeholder and preserves the URL', () => {
        const event = {
            type: 2,
            timestamp: 1,
            data: {
                node: {
                    type: 0,
                    id: 1,
                    childNodes: [
                        {
                            type: 2,
                            id: 2,
                            tagName: 'img',
                            attributes: { src: 'https://example.com/u/abc.png', alt: 'profile photo of user' },
                            childNodes: [],
                        },
                    ],
                },
                initialOffset: { top: 0, left: 0 },
            },
        }
        scrubFullSnapshot(ctx, event.data)
        const img = event.data.node.childNodes[0]
        expect(typeof img.attributes.src).toBe('string')
        expect((img.attributes.src as string).startsWith('data:image/svg+xml')).toBe(true)
        expect('data-original-src' in img.attributes).toBe(true)
    })

    it('text-scrubs string data-* attributes but leaves data-original-* blur stashes alone', () => {
        const attrs: Record<string, unknown> = {
            'data-customer': 'Smithson',
            'data-original-src': 'https://example.com/u/abc.png',
        }
        scrubMutation(ctx, { source: 0, attributes: [{ id: 2, attributes: attrs }] })
        // Author-controlled data-* is now scrubbed (was passed through verbatim before)...
        expect(attrs['data-customer']).not.toContain('Smithson')
        // ...but our own URL-scrubbed blur stash is left intact.
        expect(attrs['data-original-src']).toBe('https://example.com/u/abc.png')
    })

    it('scrubs url() targets in an inline style attribute and in <style> css text', () => {
        const attrs: Record<string, unknown> = { style: 'background: url(/users/SecretUser/bg.png)' }
        scrubMutation(ctx, { source: 0, attributes: [{ id: 2, attributes: attrs }] })
        expect(attrs.style).not.toContain('SecretUser')

        const event = {
            type: 2,
            timestamp: 1,
            data: {
                node: {
                    type: 0,
                    id: 1,
                    childNodes: [
                        {
                            type: 2,
                            id: 2,
                            tagName: 'style',
                            attributes: {},
                            childNodes: [
                                { type: 3, id: 3, textContent: '.a { background: url(/users/SecretUser/x.png) }' },
                            ],
                        },
                    ],
                },
                initialOffset: { top: 0, left: 0 },
            },
        }
        scrubFullSnapshot(ctx, event.data)
        expect(event.data.node.childNodes[0].childNodes[0].textContent).not.toContain('SecretUser')
    })
})
