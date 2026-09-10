import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { PaginationControl } from './PaginationControl'

describe('PaginationControl', () => {
    it('renders a lower-bound entry count with a trailing plus', () => {
        render(
            <PaginationControl
                pagination={{
                    controlled: true,
                    pageSize: 2,
                    currentPage: 1,
                    entryCount: 3,
                    entryCountIsLowerBound: true,
                }}
                currentPage={1}
                setCurrentPage={() => {}}
                pageCount={2}
                dataSourcePage={['a', 'b']}
                entryCount={3}
                entryCountIsLowerBound={true}
                currentStartIndex={0}
                currentEndIndex={2}
            />
        )
        expect(screen.getByText('1-2 of 3+ entries')).toBeInTheDocument()
    })
})
