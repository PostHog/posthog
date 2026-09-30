import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { PaginationControl } from './PaginationControl'
import { PaginationManual } from './types'
import { usePagination } from './usePagination'

const DATA = ['a', 'b', 'c']

const Harness = ({ pagination }: { pagination: PaginationManual }): JSX.Element => (
    <PaginationControl {...usePagination(DATA, pagination)} />
)

describe('PaginationControl', () => {
    beforeEach(() => {
        initKeaTests()
        router.actions.push('/table')
    })

    afterEach(cleanup)

    it.each<[string, number, number]>([
        ['Next page', 2, 3],
        ['Previous page', 3, 2],
    ])('%s moves one page when the controlled caller reports no entry count', (label, currentPage, expectedPage) => {
        render(
            <Harness
                pagination={{
                    controlled: true,
                    pageSize: 1,
                    currentPage,
                    onForward: () => {},
                    onBackward: () => {},
                }}
            />
        )

        fireEvent.click(screen.getByLabelText(label))

        expect(router.values.searchParams.page).toBe(expectedPage)
    })
})
