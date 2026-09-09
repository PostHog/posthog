import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { AccountDetailActions } from './AccountDetailActions'

jest.mock('lib/lemon-ui/LemonDialog', () => ({ LemonDialog: { open: jest.fn() } }))

describe('AccountDetailActions', () => {
    beforeEach(jest.clearAllMocks)
    afterEach(cleanup)

    it.each(['Configure tabs', 'Add view'])('opens a work-in-progress dialog for %s', (title) => {
        render(<AccountDetailActions />)

        fireEvent.click(screen.getByText(title))

        expect(LemonDialog.open).toHaveBeenCalledWith({
            title,
            content: 'This feature is a work in progress.',
        })
    })
})
