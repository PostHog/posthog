import { withInertLinks } from './emailPreviewHtml'

describe('withInertLinks', () => {
    const targetsOf = (html: string): (string | null)[] =>
        Array.from(new DOMParser().parseFromString(html, 'text/html').querySelectorAll('a, area')).map((link) =>
            link.getAttribute('target')
        )

    it.each([
        ['no target', '<p><a href="https://example.com/a">a</a></p>'],
        ['same tab target', '<p><a target="_self" href="https://example.com/a">a</a></p>'],
        ['parent target', '<p><a target="_top" href="https://example.com/a">a</a></p>'],
        ['image map area', '<map name="m"><area target="_self" href="https://example.com/a" /></map>'],
    ])('opens a link with %s in a blocked popup', (_, html) => {
        expect(targetsOf(withInertLinks(html)!)).toEqual(['_blank'])
    })

    it('keeps the doctype first so the preview keeps its document mode', () => {
        const result = withInertLinks('<!DOCTYPE html><html><body><a href="https://example.com">a</a></body></html>')

        expect(result).toMatch(/^<!DOCTYPE html><html>/)
    })

    it.each([[undefined], ['']])('passes %p through', (html) => {
        expect(withInertLinks(html)).toBe(html)
    })
})
