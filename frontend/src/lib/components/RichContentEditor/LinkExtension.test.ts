import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'

import { LinkExtension } from './LinkExtension'

describe('LinkExtension', () => {
    function pastedHref(text: string): string | null {
        const editor = new Editor({
            element: document.createElement('div'),
            extensions: [StarterKit.configure({ link: false }), LinkExtension],
        })
        try {
            editor.view.pasteText(text, new Event('paste') as ClipboardEvent)
            return editor.getHTML().match(/<a[^>]+href="([^"]+)"/)?.[1] ?? null
        } finally {
            editor.destroy()
        }
    }

    it.each([
        ['person.properties.plan', null],
        ['event.properties.$browser', null],
        ['person.properties.email', null],
        ['props.name', null],
        ['see person.properties.plan in the payload', null],
        // Rare TLDs lose autolinking as a side effect — an explicit scheme still works
        ['acme.solutions', null],
        ['https://acme.solutions', 'https://acme.solutions'],
        ['http://person.properties/path', 'http://person.properties/path'],
        ['https://posthog.com/docs', 'https://posthog.com/docs'],
        ['posthog.com', 'http://posthog.com'],
        ['www.posthog.com', 'http://www.posthog.com'],
        ['ask support@posthog.com', 'mailto:support@posthog.com'],
    ])('pasting %j links %j', (text, expected) => {
        expect(pastedHref(text)).toEqual(expected)
    })
})
