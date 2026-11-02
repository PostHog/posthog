import { textCardConverter } from 'lib/components/Cards/TextCard/textCardMarkdown'

import { ImageTileImage, getImageOnlyTextCardImage, imageTileToMarkdown } from './imageTileUtils'

describe('imageTileUtils', () => {
    it.each([
        ['markdown image', '![A diagram](https://example.com/diagram.png)', 'A diagram', 'contain'],
        ['HTML image', '<img src="https://example.com/diagram.png" alt="A diagram" />', 'A diagram', 'contain'],
        [
            'markdown image with blank lines',
            '\n\n![A diagram](https://example.com/diagram.png)\n',
            'A diagram',
            'contain',
        ],
        [
            'HTML image in a paragraph',
            '<p><img src="https://example.com/diagram.png" alt="A diagram"></p>',
            'A diagram',
            'contain',
        ],
    ])('detects an image-only text card from %s', (_name, markdown, alt, layout) => {
        expect(getImageOnlyTextCardImage(markdown)).toMatchObject({
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
        ['image in a list', '- ![A diagram](https://example.com/diagram.png)'],
        ['HTML image without a source', '<img alt="A diagram" />'],
        ['HTML image with a caption', '<img src="https://example.com/diagram.png" alt="A diagram" /> A caption'],
        ['empty body', ''],
        ['missing body', null],
    ])('keeps %s as a text card', (_name, markdown) => {
        expect(getImageOnlyTextCardImage(markdown)).toBeNull()
    })

    // The text card editor writes image markdown and the dashboard reads it back without the editor,
    // so every image the editor can write must parse to the same image.
    it.each<[string, Pick<ImageTileImage, 'src' | 'alt'> & Partial<ImageTileImage>, string]>([
        [
            'contain layout',
            { src: 'https://example.com/diagram.png', alt: 'A diagram' },
            '![A diagram](https://example.com/diagram.png)',
        ],
        [
            'title',
            { src: 'https://example.com/diagram.png', alt: 'A diagram', title: 'The title' },
            '![A diagram](https://example.com/diagram.png "The title")',
        ],
        [
            'cover layout',
            { src: 'https://example.com/diagram.png', alt: 'A diagram', layout: 'cover' },
            '<img src="https://example.com/diagram.png" alt="A diagram" data-layout="cover" />',
        ],
        [
            'custom position',
            {
                src: 'https://example.com/diagram.png',
                alt: 'A diagram',
                layout: 'cover',
                position: { x: 25, y: 75 },
            },
            '<img src="https://example.com/diagram.png" alt="A diagram" data-layout="cover" data-position-x="25" data-position-y="75" />',
        ],
        [
            'size',
            { src: 'https://example.com/diagram.png', alt: 'A diagram', width: '320', height: '240' },
            '<img src="https://example.com/diagram.png" alt="A diagram" width="320" height="240" />',
        ],
        [
            'bracket in the description',
            { src: 'https://example.com/diagram.png', alt: 'A ] diagram' },
            '![A \\] diagram](https://example.com/diagram.png)',
        ],
        [
            'backslash in the description',
            { src: 'https://example.com/diagram.png', alt: 'A \\ diagram' },
            '<img src="https://example.com/diagram.png" alt="A \\ diagram" />',
        ],
        [
            'quote in the title',
            { src: 'https://example.com/diagram.png', alt: 'A diagram', title: 'A "quoted" title' },
            '<img src="https://example.com/diagram.png" alt="A diagram" title="A &quot;quoted&quot; title" />',
        ],
    ])('reads back an image the editor writes with %s', (_name, image, expectedMarkdown) => {
        const markdown = imageTileToMarkdown(textCardConverter, image)

        expect(markdown).toBe(expectedMarkdown)
        expect(textCardConverter.isRoundTripSafe(markdown)).toBe(true)
        expect(getImageOnlyTextCardImage(markdown)).toEqual({
            src: image.src,
            alt: image.alt,
            title: image.title ?? '',
            layout: image.layout ?? 'contain',
            position: image.position ?? { x: 50, y: 50 },
            width: image.width ?? null,
            height: image.height ?? null,
        })
    })

    it('clamps malformed image positions to the frame', () => {
        expect(
            getImageOnlyTextCardImage(
                '<img src="https://example.com/diagram.png" alt="A diagram" data-position-x="120" data-position-y="-20" />'
            )
        ).toMatchObject({ position: { x: 100, y: 0 } })
    })
})
