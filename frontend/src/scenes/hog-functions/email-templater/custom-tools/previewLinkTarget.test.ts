import { previewLinkTargetCustomJs } from './previewLinkTarget'

describe('previewLinkTargetCustomJs', () => {
    // The customJS runs as a string inside Unlayer's iframe, so typecheck cannot see it. Run it
    // against this document and add a preview iframe the way Unlayer does.
    async function clickLinkInPreview(linkHtml: string): Promise<HTMLAnchorElement> {
        new Function(previewLinkTargetCustomJs)()

        const frame = document.createElement('iframe')
        document.body.appendChild(frame)
        await new Promise((resolve) => setTimeout(resolve, 0))

        const frameDocument = frame.contentDocument as Document
        frameDocument.body.innerHTML = linkHtml
        const link = frameDocument.querySelector('a') as HTMLAnchorElement
        link.addEventListener('click', (event) => event.preventDefault())
        const clickTarget = (frameDocument.querySelector('a *') as HTMLElement | null) ?? link
        clickTarget.click()
        return link
    }

    afterEach(() => {
        document.body.innerHTML = ''
    })

    it.each([
        ['a same-tab link', '<a href="https://www.facebook.com" target="_self">Go</a>'],
        ['a link with no target', '<a href="https://www.facebook.com">Go</a>'],
        ['a click on an element inside a link', '<a href="https://www.facebook.com" target="_top"><span>Go</span></a>'],
    ])('opens %s in a new tab', async (_name, linkHtml) => {
        const link = await clickLinkInPreview(linkHtml)
        expect(link.getAttribute('target')).toEqual('_blank')
    })
})
