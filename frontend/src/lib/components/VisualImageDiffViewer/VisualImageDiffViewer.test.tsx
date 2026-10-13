import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { type DiffOverlayBand, VisualImageDiffViewer } from './VisualImageDiffViewer'

describe('VisualImageDiffViewer', () => {
    afterEach(() => {
        cleanup()
    })

    it.each<[string, string, string]>([
        ['before image', 'View before snapshot full screen', '/before.png'],
        ['after image', 'View after snapshot full screen', '/after.png'],
    ])('opens the clicked %s in a full-screen modal', async (_imageName, accessibleName, expectedUrl) => {
        const user = userEvent.setup()

        render(
            <VisualImageDiffViewer
                baselineUrl="/before.png"
                currentUrl="/after.png"
                diffUrl={null}
                diffPercentage={1}
                result="changed"
            />
        )

        await user.click(screen.getByLabelText(accessibleName))

        const zoomedImage = document.querySelector('[data-attr="visual-review-zoomed-image"] img')
        expect(zoomedImage).toHaveAttribute('src', expectedUrl)
    })

    it.each<[string, DiffOverlayBand, string, string]>([
        ['fills the rows an insert added', { y: 10, rows: 20, kind: 'inserted' }, '10', '20'],
        ['draws a deletion as a seam instead of a region', { y: 40, rows: 20, kind: 'deleted' }, '40', '3'],
        ['keeps a deletion at the bottom edge in frame', { y: 100, rows: 20, kind: 'deleted' }, '97', '3'],
    ])('%s', (_case, band, expectedY, expectedHeight) => {
        render(
            <VisualImageDiffViewer
                baselineUrl="/before.png"
                currentUrl="/after.png"
                diffUrl="/diff.png"
                diffPercentage={1}
                result="changed"
                mode="diff"
                imageWidth={100}
                imageHeight={100}
                diffOverlayBands={[band]}
            />
        )

        const bandRect = document.querySelector('svg[viewBox="0 0 100 100"] rect')
        expect(bandRect).toHaveAttribute('y', expectedY)
        expect(bandRect).toHaveAttribute('height', expectedHeight)
    })

    // With a 100x200 baseline and a 100x100 current the shared canvas is 100x200.
    // An aligned diff is recorded at the current size and must cover half of it;
    // an unaligned diff is recorded at the padded canvas size and must fill it.
    it.each<[string, number, string, string | null]>([
        ['maps a current-sized diff onto the shorter current image', 100, '50%', '50%'],
        ['leaves a union-sized diff filling the shared canvas', 200, '100%', null],
    ])('%s', async (_case, diffHeight, expectedDiffHeight, expectedOverlayHeight) => {
        const user = userEvent.setup()

        render(
            <VisualImageDiffViewer
                baselineUrl="/before.png"
                currentUrl="/after.png"
                diffUrl="/diff.png"
                diffPercentage={1}
                result="changed"
                mode="blend"
                imageWidth={100}
                imageHeight={100}
                baselineWidth={100}
                baselineHeight={200}
                currentWidth={100}
                currentHeight={100}
                diffOverlayWidth={100}
                diffOverlayHeight={diffHeight}
                diffOverlayBands={[{ y: 40, rows: 5, kind: 'inserted' }]}
            />
        )

        await user.click(screen.getByLabelText('Diff overlay'))
        expect(screen.getByAltText('Diff overlay').style.height).toBe(expectedDiffHeight)

        // A union-sized diff puts the bands in coords that match neither image,
        // so the viewer skips the overlay instead of placing it wrongly.
        const overlayLayer = document.querySelector(`svg[viewBox="0 0 100 ${diffHeight}"]`)?.parentElement
        expect(overlayLayer?.style.height ?? null).toBe(expectedOverlayHeight)
    })
})
