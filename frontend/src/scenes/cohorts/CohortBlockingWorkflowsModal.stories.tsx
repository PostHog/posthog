import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { CohortBlockingWorkflowsModal } from './CohortBlockingWorkflowsModal'
import { CohortBlockingWorkflows, cohortBlockingWorkflowsModalLogic } from './cohortBlockingWorkflowsModalLogic'

const meta: Meta = {
    title: 'Scenes-App/People/Cohorts/Blocking Workflows Modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04',
    },
}
export default meta

type Story = StoryObj<{}>

function OpenModal({ blocking }: { blocking: CohortBlockingWorkflows }): JSX.Element {
    const { openBlockingWorkflowsModal } = useActions(cohortBlockingWorkflowsModalLogic)
    useEffect(() => {
        openBlockingWorkflowsModal(blocking)
    }, [blocking, openBlockingWorkflowsModal])
    return <CohortBlockingWorkflowsModal />
}

export const DeleteBlocked: Story = {
    render: () => (
        <OpenModal
            blocking={{
                action: 'delete',
                workflows: {
                    results: [
                        { id: '0190a1b2-0000-0000-0000-000000000001', name: 'Welcome series', status: 'active' },
                        {
                            id: '0190a1b2-0000-0000-0000-000000000002',
                            name: 'Win back churned users',
                            status: 'active',
                        },
                    ],
                    total: 3,
                    hidden: 1,
                    has_more: true,
                },
            }}
        />
    ),
}

export const EditBlocked: Story = {
    render: () => (
        <OpenModal
            blocking={{
                action: 'edit',
                workflows: {
                    results: [{ id: '0190a1b2-0000-0000-0000-000000000001', name: 'Welcome series', status: 'active' }],
                    total: 1,
                    hidden: 0,
                    has_more: false,
                },
            }}
        />
    ),
}

export const LockedFromDetails: Story = {
    render: () => (
        <OpenModal
            blocking={{
                action: 'view',
                workflows: {
                    results: [
                        { id: '0190a1b2-0000-0000-0000-000000000001', name: 'Welcome series', status: 'active' },
                        {
                            id: '0190a1b2-0000-0000-0000-000000000002',
                            name: 'Win back churned users',
                            status: 'active',
                        },
                    ],
                    total: 2,
                    hidden: 0,
                    has_more: false,
                },
            }}
        />
    ),
}
