import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { mockIntegration } from '~/test/mocks'

import { OtherIntegrations } from './OtherIntegrations'

type StoryArgs = { connected?: boolean }

const meta: Meta<StoryArgs> = {
    title: 'Components/Integrations/Other integrations',
    parameters: { mockDate: '2023-01-01' },
    render: ({ connected = false }) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations': {
                    results: connected ? [{ ...mockIntegration, kind: 'aws-s3', display_name: 'Data lake' }] : [],
                },
            },
        })

        return <OtherIntegrations />
    },
}
export default meta

type Story = StoryObj<StoryArgs>

export const Empty: Story = {}

export const Connected: Story = {
    args: { connected: true },
}
