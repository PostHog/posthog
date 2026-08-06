import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { CopyToClipboardInline } from './CopyToClipboard'

jest.mock('lib/utils/copyToClipboard')

describe('CopyToClipboardInline', () => {
    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    // The person-page copy icon renders with `selectable` and no children. The button used to have
    // no accessible name and no way to signal a successful copy — a screen-reader dead end.
    it('icon-only button copies, exposes an accessible name, and announces success', async () => {
        jest.mocked(copyToClipboard).mockResolvedValue(true)

        render(<CopyToClipboardInline selectable explicitValue="the-value" description="property value" />)

        const button = screen.getByRole('button', { name: 'Copy property value' })
        await userEvent.click(button)

        expect(copyToClipboard).toHaveBeenCalledWith('the-value', 'property value')
        await waitFor(() => expect(screen.getByText('Copied property value to clipboard')).toBeInTheDocument())
    })

    // A failed clipboard write must not leave a misleading "copied" announcement.
    it('does not announce success when the copy fails', async () => {
        jest.mocked(copyToClipboard).mockResolvedValue(false)

        render(<CopyToClipboardInline selectable explicitValue="the-value" description="property value" />)

        await userEvent.click(screen.getByRole('button', { name: 'Copy property value' }))

        expect(copyToClipboard).toHaveBeenCalled()
        await waitFor(() => expect(copyToClipboard).toHaveReturned())
        expect(screen.queryByText('Copied property value to clipboard')).not.toBeInTheDocument()
    })
})
