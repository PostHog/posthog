import { render, screen } from '@testing-library/react'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { BOOK_ACTIVITY_MATRIX_MOCK } from '../../__mocks__/bookActivityMatrixMock'
import { ProductUsageGrid } from './ProductUsageGrid'
import { productUsageGridLogic } from './productUsageGridLogic'

describe('ProductUsageGrid', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    it.each([
        ['no_group_type', 'Choose an account group type in Customer analytics settings to see activity here.'],
        ['empty_book', 'No linked account is available. Check the account link and your access.'],
    ] as const)('shows setup guidance instead of zero activity for %s', (emptyReason, message) => {
        const logic = productUsageGridLogic()
        logic.mount()
        logic.actions.finishLoad({
            accounts: { kind: NodeKind.AccountsTableQuery, results: [], hasMore: false, limit: 200, offset: 0 },
            matrix: { ...BOOK_ACTIVITY_MATRIX_MOCK, emptyReason, data: [], combinations: [], firstUse: [] },
            hogql: null,
            source: { kind: 'product_usage' },
        })
        const { container, unmount } = render(<ProductUsageGrid />)
        expect(screen.getAllByText(message)[0]).toBeInTheDocument()
        expect(container.querySelector('[data-attr="product-activity-grid"]')).toBeNull()
        unmount()
        logic.unmount()
    })
})
