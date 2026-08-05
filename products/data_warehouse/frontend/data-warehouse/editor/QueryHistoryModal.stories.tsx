import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { ActivityScope } from '~/types'

import { editorSceneLogic } from './editorSceneLogic'
import { QueryHistoryModal } from './QueryHistoryModal'
import { sqlEditorLogic } from './sqlEditorLogic'

const STORY_TAB_ID = 'story-query-history'

// Opens the modal immediately so the story renders it in the open state
function OpenQueryHistoryModal(): JSX.Element {
    const { openHistoryModal } = useActions(editorSceneLogic({ tabId: STORY_TAB_ID }))
    const { updateTab } = useActions(sqlEditorLogic({ tabId: STORY_TAB_ID }))
    useEffect(() => {
        updateTab({
            uri: { toString: () => 'story-uri' } as any,
            name: 'revenue_by_day',
            view: { id: 'view-1' } as any,
        })
        openHistoryModal()
    }, [openHistoryModal, updateTab])
    return (
        <BindLogic logic={editorSceneLogic} props={{ tabId: STORY_TAB_ID }}>
            <BindLogic logic={sqlEditorLogic} props={{ tabId: STORY_TAB_ID }}>
                <QueryHistoryModal />
            </BindLogic>
        </BindLogic>
    )
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
                '/api/environments/:team_id/warehouse_saved_queries/:id/activity': () => [
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
                '/api/environments/:team_id/warehouse_saved_queries/:id/activity': () => [
                    200,
                    { results: [], count: 0 },
                ],
            },
        }),
    ],
}
