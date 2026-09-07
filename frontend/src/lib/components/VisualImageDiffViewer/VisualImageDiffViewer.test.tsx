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

    it('draws the diff and its overlays over a shorter current image, not the whole canvas', async () => {
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
                diffOverlayBands={[{ y: 40, rows: 5, kind: 'inserted' }]}
            />
        )

        const overlayLayer = document.querySelector('svg[viewBox="0 0 100 100"]')?.parentElement
        expect(overlayLayer).toHaveStyle({ height: '50%' })

        await user.click(screen.getByLabelText('Diff overlay'))
        expect(screen.getByAltText('Diff overlay')).toHaveStyle({ height: '50%' })
    })
})
