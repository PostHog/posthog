import type { Meta, StoryObj } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import __dashboard_template_schema from 'scenes/dashboard/__mocks__/dashboard_template_schema.json'
import __dashboard_templates from 'scenes/dashboard/__mocks__/dashboard_templates.json'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { NewDashboardModal as NewDashboardModalComponent } from 'scenes/dashboard/NewDashboardModal'

import { mswDecorator } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { BaseMathType, EntityTypes } from '~/types'

const meta: Meta<typeof NewDashboardModalComponent> = {
    component: NewDashboardModalComponent,
    title: 'Products/Dashboards',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/dashboard_templates/': __dashboard_templates as any,
                '/api/projects/:team_id/dashboard_templates/json_schema/': __dashboard_template_schema as any,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
    },
}

export default meta

type Story = StoryObj<typeof NewDashboardModalComponent>

export const NewDashboardModal: Story = {
    render: () => {
        useAvailableFeatures([])
        useDelayedOnMountEffect(() => {
            newDashboardLogic.actions.showNewDashboardModal()
        })

        return <NewDashboardModalComponent />
    },
}

export const NewSelectVariables: Story = {
    render: () => {
        useAvailableFeatures([])
        useDelayedOnMountEffect(() => {
            newDashboardLogic.actions.showNewDashboardModal()
            newDashboardLogic.actions.setActiveDashboardTemplate({
                id: '1',
                template_name: 'Dashboard name',
                dashboard_description: 'The dashboard description',
                dashboard_filters: {},
                tiles: [],
                variables: [
                    {
                        id: 'SIGN_UP',
                        name: 'Sign up page viewed',
                        type: 'event',
                        default: {
                            id: '$pageview',
                            math: BaseMathType.UniqueUsers,
                            type: EntityTypes.EVENTS,
                        },
                        required: true,
                        description: 'Add the current_url filter that matches your sign up page',
                    },
                    {
                        id: 'ACTIVATED',
                        name: 'Very very long event name very very long. Very very long event name very very long',
                        type: 'event',
                        default: {
                            id: '$pageview',
                            math: BaseMathType.UniqueUsers,
                            type: EntityTypes.EVENTS,
                        },
                        required: true,
                        description:
                            'Very long description. Select the event which best represents when a user is activated. Select the event which best represents when a user is activated',
                    },
                    {
                        id: 'ACTIVATED_OPTIONAL',
                        name: 'Activated event',
                        type: 'event',
                        default: {
                            id: '$pageview',
                            math: BaseMathType.UniqueUsers,
                            type: EntityTypes.EVENTS,
                        },
                        required: false,
                        description: 'Select the event which best represents when a user is activated',
                    },
                ],
                tags: [],
                image_url: undefined,
            })
        })

        return <NewDashboardModalComponent />
    },
}
