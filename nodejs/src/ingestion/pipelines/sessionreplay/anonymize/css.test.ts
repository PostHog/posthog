import { runBlurJobs } from './blur'
import { scrubCssImages } from './css'
import { defaultAllowLists } from './default-dict'

// A small patterned PNG.
const ONE_PX =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAACXBIWXMAAAPoAAAD6AG1e1JrAAAAJUlEQVQokWN4plEBRyInbOAIlzjDINRAjCJk8cGoYRAG60iMBwA8H08Qor0ygQAAAABJRU5ErkJggg=='

function ctx(): { allow: ReturnType<typeof defaultAllowLists>; blurJobs: any[] } {
    return { allow: defaultAllowLists(), blurJobs: [] }
}

describe('anonymize/css', () => {
    it('blurs url(data:image) backgrounds, leaving sprite/remote/non-data url() untouched', () => {
        const c = ctx()
        const node: Record<string, unknown> = {
            textContent: `.a{background:url(${ONE_PX})} .b{background:url(/assets/sprite.svg#icon)} .c{mask:url("https://cdn.example.com/m.png")}`,
        }
        expect(scrubCssImages(c, node, 'textContent')).toBe(true)
        const css = node.textContent as string
        expect(css).not.toContain(ONE_PX) // raw image gone synchronously
        expect(css).toContain('/assets/sprite.svg#icon') // sprite fragment untouched
        expect(css).toContain('https://cdn.example.com/m.png') // remote url untouched
        expect(c.blurJobs).toHaveLength(1)
    })

    it('leaves CSS with no inline data-image unchanged', () => {
        const c = ctx()
        const node = { textContent: '.a{background:url(/img/x.png)}' }
        expect(scrubCssImages(c, node, 'textContent')).toBe(false)
        expect(node.textContent).toBe('.a{background:url(/img/x.png)}')
        expect(c.blurJobs).toHaveLength(0)
    })

    it('resolves the placeholder to a blurred png after the deferred job runs', async () => {
        const c = ctx()
        const node: Record<string, unknown> = { textContent: `.a{background:url(${ONE_PX})}` }
        scrubCssImages(c, node, 'textContent')
        await runBlurJobs(c.blurJobs)
        const css = node.textContent as string
        expect(css).toMatch(/url\(data:image\/png;base64,[A-Za-z0-9+/=]+\)/)
        expect(css).not.toContain('#a0') // unique placeholder fragment resolved
        expect(css).not.toContain(ONE_PX) // not the original
    })
})
