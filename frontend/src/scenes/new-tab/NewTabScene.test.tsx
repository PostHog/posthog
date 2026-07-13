import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useValues } from 'kea'
import { router } from 'kea-router'

import { NewTabScene } from './NewTabScene'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
}))

jest.mock('kea-router', () => ({
    ...jest.requireActual('kea-router'),
    router: { actions: { push: jest.fn() } },
}))

const mockActionOnSelect = jest.fn()

// Stand in for the Search launcher: expose one button per item kind that calls
// the `onItemSelect` NewTabScene wires up, exactly as a real click in the list would.
jest.mock('lib/components/Search/Search', () => ({
    Search: {
        Root: ({
            children,
            onItemSelect,
        }: {
            children: React.ReactNode
            onItemSelect: (item: {
                id: string
                name: string
                category: string
                href?: string
                onSelect?: () => void
            }) => void
        }) => (
            <div>
                <button
                    onClick={() =>
                        onItemSelect({ id: 'sql', name: 'SQL editor', category: 'suggested', href: '/sql-editor' })
                    }
                >
                    select-href-item
                </button>
                <button
                    onClick={() =>
                        onItemSelect({ id: 'logout', name: 'Log out', category: 'misc', onSelect: mockActionOnSelect })
                    }
                >
                    select-action-item
                </button>
                {children}
            </div>
        ),
        Input: () => <div />,
        Status: () => <div />,
        Separator: () => <div />,
        Results: () => <div />,
    },
}))

const mockedUseValues = useValues as jest.Mock
const mockedRouterPush = router.actions.push as jest.Mock

describe('NewTabScene', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        mockedUseValues.mockReturnValue({ searchParams: {} })
    })

    afterEach(() => {
        cleanup()
    })

    it('navigates to the item href when a link item is selected', async () => {
        render(<NewTabScene />)

        await userEvent.click(screen.getByText('select-href-item'))

        expect(mockedRouterPush).toHaveBeenCalledWith('/sql-editor')
        expect(mockActionOnSelect).not.toHaveBeenCalled()
    })

    it('invokes onSelect when an action item without an href is selected', async () => {
        render(<NewTabScene />)

        await userEvent.click(screen.getByText('select-action-item'))

        expect(mockActionOnSelect).toHaveBeenCalledTimes(1)
        expect(mockedRouterPush).not.toHaveBeenCalled()
    })
})
