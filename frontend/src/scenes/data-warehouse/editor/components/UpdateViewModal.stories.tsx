import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { sqlEditorLogic } from '../sqlEditorLogic'
import { UpdateViewModal } from './UpdateViewModal'

const SAVED_QUERY = 'SELECT date, sum(revenue) AS revenue\nFROM orders\nGROUP BY date'
const EDITED_QUERY = "SELECT date, sum(revenue) AS revenue\nFROM orders\nWHERE status = 'paid'\nGROUP BY date"

// Opens the modal immediately so the story renders it with a diff to review
function OpenUpdateViewModal({ tabId, isMaterialized }: { tabId: string; isMaterialized: boolean }): JSX.Element {
    const { updateTab, setQueryInput, openUpdateViewModal } = useActions(sqlEditorLogic({ tabId }))
    useEffect(() => {
        updateTab({
            uri: { toString: () => 'story-uri' } as any,
            name: 'revenue_by_day',
            view: {
                id: 'view-1',
                name: 'revenue_by_day',
                is_materialized: isMaterialized,
                query: { query: SAVED_QUERY },
            } as any,
        })
        setQueryInput(EDITED_QUERY)
        openUpdateViewModal({ id: 'view-1', query: { query: EDITED_QUERY } as any, types: [] })
    }, [updateTab, setQueryInput, openUpdateViewModal, isMaterialized])
    return (
        <BindLogic logic={sqlEditorLogic} props={{ tabId }}>
            <UpdateViewModal />
        </BindLogic>
    )
}

type Story = StoryObj<typeof UpdateViewModal>
const meta: Meta<typeof UpdateViewModal> = {
    title: 'Data Warehouse/Update view modal',
    component: UpdateViewModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}

export default meta

export const View: Story = {
    render: () => <OpenUpdateViewModal tabId="story-update-view" isMaterialized={false} />,
}

export const MaterializedView: Story = {
    render: () => <OpenUpdateViewModal tabId="story-update-materialized-view" isMaterialized={true} />,
}
