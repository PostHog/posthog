import { Meta, StoryObj } from '@storybook/react'
import { NewMetricForm } from './NewMetricForm'
import { mswDecorator } from '~/mocks/browser'

const eventDefinitions = [
    {
        id: '017cdbec-c38f-0000-1479-bc7b9e2b6c77',
        name: 'purchase',
        description: 'When a user completes a purchase',
    },
    {
        id: '017ce199-a10e-0000-6783-7167743302f4',
        name: 'signup',
        description: 'When a user signs up',
    },
    {
        id: '017cdbee-0c77-0000-ecf1-bd5a9e253b92',
        name: 'page_view',
        description: 'When a user views a page',
    },
]

const meta: Meta<typeof NewMetricForm> = {
    title: 'Scenes-App/Experiments/NewMetricForm',
    component: NewMetricForm,
    parameters: {
        mockDate: '2024-01-01',
        layout: 'centered',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id': { id: 2 },
                '/api/projects/:team_id/event_definitions': {
                    count: eventDefinitions.length,
                    next: null,
                    previous: null,
                    results: eventDefinitions,
                },
            },
        }),
    ],
}

export default meta
type Story = StoryObj<typeof NewMetricForm>

export const Primary: Story = {
    args: {
        isOpen: true,
        onClose: () => {},
        isSecondary: false,
    },
}

export const SecondaryMetric: Story = {
    args: {
        isOpen: true,
        onClose: () => {},
        isSecondary: true,
    },
}
