import { EmbedExtension } from './EmbedExtension'

type RenderResult = unknown[]

function renderEmbedHTML(attrs: Record<string, unknown>): RenderResult {
    const config = (
        EmbedExtension as unknown as {
            config: { renderHTML: (args: { HTMLAttributes: Record<string, unknown> }) => RenderResult }
        }
    ).config
    return config.renderHTML.call({ options: { HTMLAttributes: {} } } as ThisParameterType<typeof config.renderHTML>, {
        HTMLAttributes: attrs,
    })
}

function findIframe(tree: unknown): unknown[] | null {
    if (!Array.isArray(tree)) {
        return null
    }
    if (tree[0] === 'iframe') {
        return tree as unknown[]
    }
    for (const child of tree) {
        const found = findIframe(child)
        if (found) {
            return found
        }
    }
    return null
}

describe('EmbedExtension.renderHTML (VERIA-305)', () => {
    it.each([
        ['javascript:', 'javascript:alert(document.cookie)'],
        ['arbitrary https', 'https://attacker.example/x.html'],
        ['data:', 'data:text/html,<script>alert(1)</script>'],
        ['empty', ''],
        ['null', null],
    ])('emits no iframe for unsupported src (%s)', (_label, src) => {
        const tree = renderEmbedHTML({ src, provider: 'youtube' })
        expect(findIframe(tree)).toBeNull()
    })

    it('emits a canonical iframe src for a valid YouTube URL — never the raw input', () => {
        const tree = renderEmbedHTML({
            src: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&attacker=1',
            provider: 'youtube',
        })
        const iframe = findIframe(tree)
        expect(iframe).not.toBeNull()
        const attrs = iframe![1] as Record<string, string>
        expect(attrs.src).toBe('https://www.youtube.com/embed/dQw4w9WgXcQ')
    })
})
