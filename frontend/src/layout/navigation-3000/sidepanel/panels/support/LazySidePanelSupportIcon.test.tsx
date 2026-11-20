import { render, waitFor } from '@testing-library/react'

import { LazySidePanelSupportIcon } from './LazySidePanelSupportIcon'

jest.mock('products/conversations/frontend/components/SidePanel/SidePanelSupportIcon', () => ({
    SidePanelSupportIcon: () => {
        const error = new Error('Loading chunk SidePanelSupportIcon failed')
        error.name = 'ChunkLoadError'
        throw error
    },
}))

describe('LazySidePanelSupportIcon', () => {
    it('shows the plain support icon when the badge chunk fails', async () => {
        const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})

        const { container } = render(<LazySidePanelSupportIcon className="test-icon" />)

        // The Suspense fallback looks the same, so wait until the boundary has caught the failure.
        await waitFor(() => expect(consoleError).toHaveBeenCalled())
        expect(container.querySelector('span.test-icon svg')).not.toBeNull()
    })
})
