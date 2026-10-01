import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { PaginationControl } from './PaginationControl'

function renderLastCountedPage({
    entryCountIsLowerBound,
    onForward,
    setCurrentPage = () => {},
}: {
    entryCountIsLowerBound: boolean
    onForward?: () => void
    setCurrentPage?: (page: number) => void
}): void {
    render(
        <PaginationControl
            pagination={{
                controlled: true,
                pageSize: 2,
                currentPage: 2,
                entryCount: 4,
                entryCountIsLowerBound,
                onForward,
                onBackward: () => {},
            }}
            currentPage={2}
            setCurrentPage={setCurrentPage}
            pageCount={2}
            dataSourcePage={['c', 'd']}
            entryCount={4}
            entryCountIsLowerBound={entryCountIsLowerBound}
            currentStartIndex={2}
            currentEndIndex={4}
        />
    )
}

describe('PaginationControl', () => {
    // jest.setupAfterEnv does not enable RTL auto-cleanup; unmount between tests so `screen` stays isolated.
    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            name: 'an exact count',
            entryCountIsLowerBound: false,
            hasNextLink: true,
            label: '3-4 of 4 entries',
            next: false,
        },
        {
            name: 'a capped count',
            entryCountIsLowerBound: true,
            hasNextLink: true,
            label: '3-4 of 4+ entries',
            next: true,
        },
        {
            name: 'a capped count on the true last page',
            entryCountIsLowerBound: true,
            hasNextLink: false,
            label: '3-4 of 4+ entries',
            next: false,
        },
    ])('on the last counted page with $name', ({ entryCountIsLowerBound, hasNextLink, label, next }) => {
        renderLastCountedPage({ entryCountIsLowerBound, onForward: hasNextLink ? () => {} : undefined })

        expect(screen.getByText(label)).toBeInTheDocument()
        expect(screen.getByLabelText('Next page')).toHaveAttribute('aria-disabled', String(!next))
    })

    it('pages past a capped count', () => {
        const onForward = jest.fn()
        const setCurrentPage = jest.fn()
        renderLastCountedPage({ entryCountIsLowerBound: true, onForward, setCurrentPage })

        fireEvent.click(screen.getByLabelText('Next page'))

        expect(onForward).toHaveBeenCalledTimes(1)
        expect(setCurrentPage).toHaveBeenCalledWith(3)
    })
})
