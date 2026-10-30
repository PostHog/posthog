import { MOCK_SECOND_ORGANIZATION_MEMBER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/react'

import { mswDecorator } from '~/mocks/browser'

import { memberOffboardingLogic } from './memberOffboardingLogic'
import { MemberOffboardingModal } from './MemberOffboardingModal'

const resources = [
    {
        id: 'public_link:dashboard:1:4',
        kind: 'dashboard',
        name: 'Product adoption',
        url: '/project/1/dashboard/4',
        password_required: true,
        team_id: 1,
        project_name: 'Website',
    },
    {
        id: 'public_link:dashboard:2:5',
        kind: 'dashboard',
        name: 'Growth overview',
        url: '/project/2/dashboard/5',
        password_required: false,
        team_id: 2,
        project_name: 'App',
    },
    {
        id: 'public_link:dashboard:1:1',
        kind: 'dashboard',
        name: 'Product overview',
        url: '/project/1/dashboard/1',
        password_required: false,
        team_id: 1,
        project_name: 'Website',
    },
    {
        id: 'public_link:insight:1:2',
        kind: 'insight',
        name: 'Weekly acquisition',
        url: '/project/1/insights/trends01',
        password_required: true,
        team_id: 1,
        project_name: 'Website',
    },
    {
        id: 'public_link:notebook:2:3',
        kind: 'notebook',
        name: 'Acquisition analysis',
        url: '/project/2/notebooks/analysis',
        password_required: true,
        team_id: 2,
        project_name: 'App',
    },
]

const meta: Meta<typeof MemberOffboardingModal> = {
    title: 'Scenes-App/Settings/Organization/Member offboarding',
    component: MemberOffboardingModal,
    decorators: [
        mswDecorator({
            patch: {
                '/api/organizations/:organizationId/members/:userUuid/offboarding_resources/': () => [204, null],
            },
            get: {
                '/api/organizations/:organizationId/members/:userUuid/offboarding/': resources,
                '/api/organizations/:organizationId/members/:userUuid/scoped_api_keys/': { has_keys: false, keys: [] },
            },
        }),
    ],
    play: async () => {
        const logic = memberOffboardingLogic.build()
        logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)
        await waitFor(() => {
            if (!logic.values.resources?.length) {
                throw new Error(logic.values.loadError || 'Waiting for resource review')
            }
        })
    },
}
export default meta

type Story = StoryObj<typeof meta>
export const ReviewResources: Story = {}
export const NoResources: Story = {
    decorators: [mswDecorator({ get: { '/api/organizations/:organizationId/members/:userUuid/offboarding/': [] } })],
    play: async () => {
        const logic = memberOffboardingLogic.build()
        logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)
        await waitFor(() => {
            if (logic.values.resourcesLoading || logic.values.resources === null) {
                throw new Error(logic.values.loadError || 'Waiting for resource review')
            }
        })
    },
}
