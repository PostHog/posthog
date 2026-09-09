import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { AvailableFeature, Realm } from '~/types'

import { ProjectCreate } from './index'

type StoryProps = { projectLimit: number }

const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Scenes-Other/Project Create',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-31 12:00:00',
    },
    render: ({ projectLimit }: StoryProps) => {
        const organization = {
            // The mock organization holds one project, so a limit of 1 is the plan-limit case.
            ...MOCK_DEFAULT_ORGANIZATION,
            available_product_features: [
                {
                    key: AvailableFeature.ORGANIZATIONS_PROJECTS,
                    name: 'Projects',
                    limit: projectLimit,
                    unit: 'project',
                },
            ],
        }

        useStorybookMocks({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: Realm.Cloud },
                '/api/billing/': billingJson,
                '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, organization }],
                '/api/organizations/@current/': () => [200, organization],
                '/api/environments/@current/': () => [200, MOCK_DEFAULT_TEAM],
                '/api/projects/@current/': () => [200, MOCK_DEFAULT_TEAM],
            },
        })

        return (
            <div className="max-w-4xl p-4 mx-auto">
                <ProjectCreate />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<(props: StoryProps) => JSX.Element>

export const WithinPlanLimit: Story = {
    args: { projectLimit: 2 },
}

export const AtPlanLimit: Story = {
    args: { projectLimit: 1 },
}
