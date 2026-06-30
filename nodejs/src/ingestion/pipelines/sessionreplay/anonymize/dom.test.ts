import { defaultAllowLists } from './default-dict'
import { scrubFullSnapshot, scrubMutation } from './dom'

describe('anonymize/dom', () => {
    const ctx = { allow: defaultAllowLists() }

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
        expect('data-anon-original-src' in img.attributes).toBe(true)
    })

    it('keeps state-token data-* (so styling survives) but redacts PII-looking values and emails', () => {
        const attrs: Record<string, unknown> = {
            'data-state': 'active', // enum/state token → kept (CSS selectors depend on it)
            'data-scheme': 'primary', // ditto
            'data-tooltip': 'Logged in as Smithson', // free text (whitespace) → redacted
            'data-contact': 'jane@example.com', // email → redacted regardless
            'data-anon-original-src': 'https://example.com/[redacted]/[redacted]', // our stash → left intact
        }
        scrubMutation(ctx, { source: 0, attributes: [{ id: 2, attributes: attrs }] })
        expect(attrs['data-state']).toBe('active')
        expect(attrs['data-scheme']).toBe('primary')
        expect(attrs['data-tooltip']).not.toContain('Smithson')
        expect(attrs['data-contact']).not.toContain('jane')
        expect(attrs['data-contact']).not.toContain('example.com')
        expect(attrs['data-anon-original-src']).toBe('https://example.com/[redacted]/[redacted]')
    })

    it('leaves CSS untouched: the inline style attribute and <style> text pass through verbatim', () => {
        // CSS is author stylesheet content, not user PII; scrubbing url() targets broke far
        // more (SVG sprite fragments, CDN asset paths) than it ever saved, so we no longer touch it.
        const attrs: Record<string, unknown> = { style: 'background: url(/users/SecretUser/bg.png)' }
        expect(scrubMutation(ctx, { source: 0, attributes: [{ id: 2, attributes: attrs }] })).toBe(false)
        expect(attrs.style).toBe('background: url(/users/SecretUser/bg.png)')

        const cssText = '.a { background: url(/users/SecretUser/x.png) }'
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
                            childNodes: [{ type: 3, id: 3, textContent: cssText }],
                        },
                    ],
                },
                initialOffset: { top: 0, left: 0 },
            },
        }
        expect(scrubFullSnapshot(ctx, event.data)).toBe(false)
        expect(event.data.node.childNodes[0].childNodes[0].textContent).toBe(cssText)
    })

    it('blurs canvas pixels inlined as rr_dataURL in a FullSnapshot', () => {
        const blurCtx = { allow: defaultAllowLists(), blurJobs: [] as any[] }
        const onePxPng =
            'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAACXBIWXMAAAPoAAAD6AG1e1JrAAAAJUlEQVQokWN4plEBRyInbOAIlzjDINRAjCJk8cGoYRAG60iMBwA8H08Qor0ygQAAAABJRU5ErkJggg=='
        const canvasAttrs: Record<string, unknown> = { rr_dataURL: onePxPng, width: '300', height: '150' }
        const event = {
            type: 2,
            timestamp: 1,
            data: {
                node: {
                    type: 0,
                    id: 1,
                    childNodes: [{ type: 2, id: 2, tagName: 'canvas', attributes: canvasAttrs, childNodes: [] }],
                },
                initialOffset: { top: 0, left: 0 },
            },
        }
        expect(scrubFullSnapshot(blurCtx, event.data)).toBe(true)
        // Raw pixels gone immediately (fail-safe), blur deferred; dimensions untouched.
        expect(canvasAttrs.rr_dataURL).not.toBe(onePxPng)
        expect(canvasAttrs.rr_dataURL).toMatch(/^data:image\/png;base64,/)
        expect(canvasAttrs.width).toBe('300')
        expect(blurCtx.blurJobs).toHaveLength(1)
    })
})
