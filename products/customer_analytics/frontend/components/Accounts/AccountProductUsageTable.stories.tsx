import type { Meta, StoryObj } from '@storybook/react'

import { AccountProductUsageTable } from './AccountProductUsageTable'
import { BOOK_ACTIVITY_MATRIX_MOCK } from './bookActivityMatrixMock'

const meta: Meta<typeof AccountProductUsageTable> = {
    title: 'Customer analytics/Account product usage',
    component: AccountProductUsageTable,
    parameters: {
        layout: 'padded',
        mockDate: '2026-11-03',
        testOptions: { waitForSelector: '[data-attr="account-product-usage-table"]' },
    },
    args: {
        instanceId: 'account-product-usage-story',
        accountId: BOOK_ACTIVITY_MATRIX_MOCK.rows[0].key,
        result: {
            ...BOOK_ACTIVITY_MATRIX_MOCK,
            columns: BOOK_ACTIVITY_MATRIX_MOCK.columns.slice(-8),
            firstUse: [
                {
                    row: BOOK_ACTIVITY_MATRIX_MOCK.rows[0].key,
                    series: 'pa',
                    date: BOOK_ACTIVITY_MATRIX_MOCK.columns.at(-1)!.key,
                },
            ],
        },
        renderTopUsers: () => <span className="text-xs text-secondary">Alex, Sam, Jo</span>,
        includeFirstUse: true,
        onIncludeFirstUseChange: () => {},
    },
}
export default meta

type Story = StoryObj<typeof AccountProductUsageTable>
export const GroupedProducts: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-full max-w-lg">
                <Story />
            </div>
        ),
    ],
}
