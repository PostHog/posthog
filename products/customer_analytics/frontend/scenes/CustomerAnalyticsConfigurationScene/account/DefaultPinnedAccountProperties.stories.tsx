import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useEffect } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { mswDecorator } from '~/mocks/browser'

import { DefaultPinnedAccountProperties } from './DefaultPinnedAccountProperties'

const CUSTOM_PROPERTY_ID = '01980d7c-0000-7000-8000-000000000001'
const RELATIONSHIP_ID = '01980d7c-0000-7000-8000-000000000002'

function DefaultPinnedAccountPropertiesStory(): JSX.Element {
    useEffect(() => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            customer_analytics_config: {
                ...MOCK_DEFAULT_TEAM.customer_analytics_config,
                default_pinned_properties: [
                    { kind: 'custom_property', id: CUSTOM_PROPERTY_ID },
                    { kind: 'relationship', id: RELATIONSHIP_ID },
                ],
            },
        })
    }, [])

    return (
        <div className="max-w-240 p-6">
            <DefaultPinnedAccountProperties />
        </div>
    )
}

const meta: Meta = {
    component: DefaultPinnedAccountPropertiesStory,
    title: 'Customer Analytics/Default pinned properties',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: {
            waitForSelector: '[data-attr="account-pinned-properties-list"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/custom_property_definitions/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: CUSTOM_PROPERTY_ID,
                            name: 'Annual recurring revenue',
                            description: 'Current annual recurring revenue',
                            display_type: 'currency',
                            target_type: 'account',
                            is_canonical: false,
                            has_workflow_reference: false,
                            is_big_number: false,
                            options: null,
                            source: null,
                        },
                    ],
                },
                'api/projects/:team_id/account_relationship_definitions/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: RELATIONSHIP_ID,
                            name: 'Customer success manager',
                            description: 'The customer success manager responsible for this account',
                            is_single_holder: true,
                            is_controlled: false,
                        },
                    ],
                },
            },
        }),
    ],
}

export default meta

type Story = StoryObj<{}>

export const Configured: Story = {
    render: () => <DefaultPinnedAccountPropertiesStory />,
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Configure defaults'))
    },
}
