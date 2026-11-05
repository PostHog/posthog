import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { FeatureRequestApi } from '../../generated/api.schemas'
import { FeatureRequestCreateModal } from './FeatureRequestCreateModal'
import { FeatureRequestEditModal } from './FeatureRequestEditModal'
import { featureRequestsLogic } from './featureRequestsLogic'

const request: FeatureRequestApi = {
    id: 'feature-request-1',
    title: 'Show retention data in account reports',
    description: 'Example request used only for Storybook.',
    request_status: 'planned',
    request_priority: null,
    is_archived: false,
    archived_at: null,
    archived_by: null,
    version: 1,
    can_update: true,
    github_link: null,
    account: { id: 'account-1', name: 'Example account' },
    account_links: [],
    evidence_count: 0,
    product_areas: [],
    created_by: 1,
    updated_by: 1,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
}

function CreateModalWithErrors(): JSX.Element {
    const { openCreateRequest, submitFeatureRequestForm } = useActions(featureRequestsLogic)

    useEffect(() => {
        openCreateRequest()
        submitFeatureRequestForm()
    }, [openCreateRequest, submitFeatureRequestForm])

    return <FeatureRequestCreateModal />
}

function EditModalWithErrors(): JSX.Element {
    const { openEditRequest, setFeatureRequestEditFormValue, submitFeatureRequestEditForm } =
        useActions(featureRequestsLogic)

    useEffect(() => {
        openEditRequest(request)
        setFeatureRequestEditFormValue('title', '')
        submitFeatureRequestEditForm()
    }, [openEditRequest, setFeatureRequestEditFormValue, submitFeatureRequestEditForm])

    return <FeatureRequestEditModal />
}

const meta: Meta = {
    title: 'Customer analytics/Feature requests/Form modals',
    parameters: {
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS],
        testOptions: { snapshotTargetSelector: '.LemonModal' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/feature_requests/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/feature_requests/:id/': request,
                '/api/projects/:team_id/feature_requests/:id/history/': [],
                '/api/projects/:team_id/feature_request_product_areas/': [],
                '/api/projects/:team_id/accounts/': { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj

export const CreateMissingRequiredFields: Story = { render: () => <CreateModalWithErrors /> }

export const EditMissingRequiredFields: Story = { render: () => <EditModalWithErrors /> }
