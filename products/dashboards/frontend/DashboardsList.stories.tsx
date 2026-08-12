import type { Meta, StoryObj } from '@storybook/react'

import __dashboards from 'scenes/dashboard/__mocks__/dashboards.json'

import { mswDecorator } from '~/mocks/browser'

import { DashboardsContent } from './components/DashboardsContent'

const meta: Meta<typeof DashboardsContent> = {
    component: DashboardsContent,
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

type Story = StoryObj<typeof DashboardsContent>

export const List: Story = {}
