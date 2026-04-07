import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { ActivityScope } from '~/types'

import { QueryHistoryModal } from './QueryHistoryModal'
import { sqlEditorLogic } from './sqlEditorLogic'

// Opens the modal immediately so the story renders it in the open state
function OpenQueryHistoryModal(): JSX.Element {
    const { openHistoryModal } = useActions(sqlEditorLogic)
    useEffect(() => {
        openHistoryModal()
    }, [openHistoryModal])
    return <QueryHistoryModal />
}

const mockActivityItem = {
    user: { first_name: 'Jane', last_name: 'Doe', email: 'jane@example.com' },
    unread: false,
    is_system: false,
    activity: 'updated',
    item_id: 'view-1',
    scope: ActivityScope.DATA_WAREHOUSE_SAVED_QUERY,
    detail: {
        merge: null,
        name: 'revenue_by_day',
        type: null,
        changes: [
            {
                type: ActivityScope.DATA_WAREHOUSE_SAVED_QUERY,
                field: 'query',
                action: 'changed',
                before: { query: 'SELECT date, sum(revenue) FROM orders GROUP BY 1' },
                after: { query: "SELECT date, sum(revenue) FROM orders WHERE status = 'paid' GROUP BY 1" },
            },
        ],
        trigger: null,
        name: null,
        short_id: null,
    },
    created_at: '2024-01-15T10:00:00Z',
}

type Story = StoryObj<typeof QueryHistoryModal>
const meta: Meta<typeof QueryHistoryModal> = {
    title: 'Data Warehouse/Query history modal',
    component: QueryHistoryModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/warehouse/saved_queries/:id/activity': () => [
                    200,
                    { results: [mockActivityItem], count: 1 },
                ],
            },
        }),
    ],
    render: () => <OpenQueryHistoryModal />,
}

export default meta

export const WithHistory: Story = {}

export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/warehouse/saved_queries/:id/activity': () => [
                    200,
                    { results: [], count: 0 },
                ],
            },
        }),
    ],
}
