import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { BookActivityMatrixResult } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { BOOK_ACTIVITY_MATRIX_MOCK } from '../../__mocks__/bookActivityMatrixMock'
import { productUsageGridLogic } from './productUsageGridLogic'
import { ProductUsageUsersTable } from './ProductUsageUsersTable'

describe('ProductUsageUsersTable', () => {
    afterEach(cleanup)

    it('counts accounts in pagination while each account has product detail rows', () => {
        localStorage.clear()
        initKeaTests()
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.setControls({ selected: ['pa', 'web'] })
        const rows = ['Acorn', 'Birch', 'Cedar', 'Dahlia', 'Elm', 'Fern'].map((label) => ({
            key: label,
            externalId: label,
            label,
        }))
        const column = '2026-10-05'
        const matrix: BookActivityMatrixResult = {
            ...BOOK_ACTIVITY_MATRIX_MOCK,
            rows,
            columns: [{ key: column, partial: false }],
            series: BOOK_ACTIVITY_MATRIX_MOCK.series.filter(({ key }) => key === 'pa' || key === 'web'),
            data: rows.flatMap(({ key }) => ['pa', 'web'].map((series) => ({ row: key, column, series, users: 1 }))),
            combinations: [],
            firstUse: [],
        }
        render(<ProductUsageUsersTable matrix={matrix} views={[]} />)

        expect(screen.getByText('1-5 of 6 accounts')).toBeTruthy()
        expect(screen.getAllByText('Product analytics')).toHaveLength(5)
        expect(screen.queryByText('Fern')).toBeNull()
        fireEvent.click(screen.getByLabelText('Next page'))
        expect(screen.getByText('6 of 6 accounts')).toBeTruthy()
        expect(screen.getByText('Fern')).toBeTruthy()
        expect(screen.queryByText('Acorn')).toBeNull()
        fireEvent.click(screen.getByLabelText('Previous page'))
        expect(screen.getByText('1-5 of 6 accounts')).toBeTruthy()
        expect(screen.getByText('Acorn')).toBeTruthy()
        logic.unmount()
    })
})
