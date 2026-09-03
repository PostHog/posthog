import { textCardConverter } from 'lib/components/Cards/TextCard/textCardMarkdown'

import { getImageOnlyTextCardImage, imageTileToMarkdown } from './imageTileUtils'

describe('imageTileUtils', () => {
    it.each([
        ['markdown image', '![A diagram](https://example.com/diagram.png)', 'A diagram', 'contain'],
        ['HTML image', '<img src="https://example.com/diagram.png" alt="A diagram" />', 'A diagram', 'contain'],
    ])('detects an image-only text card from %s', (_name, markdown, alt, layout) => {
        expect(getImageOnlyTextCardImage(textCardConverter, markdown)).toMatchObject({
            src: 'https://example.com/diagram.png',
            alt,
            layout,
        })
    })

    it.each([
        ['plain text', 'A diagram'],
        ['image caption', '![A diagram](https://example.com/diagram.png)\n\nA caption'],
        ['multiple images', '![First](https://example.com/first.png)\n\n![Second](https://example.com/second.png)'],
        ['malformed image markdown', '![A diagram](https://example.com/diagram.png'],
    ])('keeps %s as a text card', (_name, markdown) => {
        expect(getImageOnlyTextCardImage(textCardConverter, markdown)).toBeNull()
    })

    it('creates image markdown through the text card converter', () => {
        const markdown = imageTileToMarkdown(textCardConverter, {
            src: 'https://example.com/diagram.png',
            alt: 'A diagram',
        })

        expect(markdown).toBe('![A diagram](https://example.com/diagram.png)')
    })

    it('preserves a cover layout through the text card converter', () => {
        const markdown = imageTileToMarkdown(textCardConverter, {
            src: 'https://example.com/diagram.png',
            alt: 'A diagram',
            layout: 'cover',
        })

        expect(markdown).toBe('<img src="https://example.com/diagram.png" alt="A diagram" data-layout="cover" />')
        expect(getImageOnlyTextCardImage(textCardConverter, markdown)).toMatchObject({ layout: 'cover' })
        expect(textCardConverter.isRoundTripSafe(markdown)).toBe(true)
    })

    it('preserves a custom image position through the text card converter', () => {
        const markdown = imageTileToMarkdown(textCardConverter, {
            src: 'https://example.com/diagram.png',
            alt: 'A diagram',
            layout: 'cover',
            position: { x: 25, y: 75 },
        })

        expect(markdown).toBe(
            '<img src="https://example.com/diagram.png" alt="A diagram" data-layout="cover" data-position-x="25" data-position-y="75" />'
        )
        expect(getImageOnlyTextCardImage(textCardConverter, markdown)).toMatchObject({ position: { x: 25, y: 75 } })
        expect(textCardConverter.isRoundTripSafe(markdown)).toBe(true)
    })

    it('clamps malformed image positions to the frame', () => {
        expect(
            getImageOnlyTextCardImage(
                textCardConverter,
                '<img src="https://example.com/diagram.png" alt="A diagram" data-position-x="120" data-position-y="-20" />'
            )
        ).toMatchObject({ position: { x: 100, y: 0 } })
    })

    it.each(['A ] diagram', 'A \\ diagram'])('preserves punctuation in image descriptions: %s', (alt) => {
        const markdown = imageTileToMarkdown(textCardConverter, {
            src: 'https://example.com/diagram.png',
            alt,
        })

        expect(getImageOnlyTextCardImage(textCardConverter, markdown)).toMatchObject({ alt })
    })
})
