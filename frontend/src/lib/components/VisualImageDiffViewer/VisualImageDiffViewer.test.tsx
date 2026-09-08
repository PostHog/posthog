import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { VisualImageDiffViewer } from './VisualImageDiffViewer'

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
})
