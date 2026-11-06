import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import __dashboards from './__mocks__/dashboards.json'
import { DashboardsTableContainer } from './dashboards/DashboardsTable'

const meta: Meta<typeof DashboardsTableContainer> = {
    component: DashboardsTableContainer,
    title: 'Products/Dashboards',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/dashboards/': __dashboards as any,
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

type Story = StoryObj<typeof DashboardsTableContainer>

export const List: Story = {}
