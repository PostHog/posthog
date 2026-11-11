import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { HistoryTableAccessSection } from './HistoryTableAccessSection'

const meta: Meta<typeof HistoryTableAccessSection> = {
    title: 'Data Warehouse/HistoryTableAccessSection',
    component: HistoryTableAccessSection,
    args: { tableId: 'table-1' },
    parameters: {
        featureFlags: [FEATURE_FLAGS.WAREHOUSE_HISTORY_ACCESS_RULES],
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/warehouse_tables/:id/history_table/': {
                    history_table: { id: 'history-1', name: 'postgres.orders_history', user_can_manage_access: true },
                },
            },
        }),
    ],
}
export default meta

export const Default: StoryObj<typeof HistoryTableAccessSection> = {}
