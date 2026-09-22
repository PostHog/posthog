import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { useStorybookMocks } from '~/mocks/browser'
import { EmailIntegrationDomainGroupedType, IntegrationType } from '~/types'

import { IntegrationEmailDomainView } from './IntegrationEmailDomainView'

const emailSender = (id: number, name: string, email: string): IntegrationType => ({
    id,
    kind: 'email',
    display_name: email,
    icon_url: '',
    config: { domain: 'example.com', name, email, verified: true, provider: 'ses' },
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
})

const senders: IntegrationType[] = [
    emailSender(42, 'Notifications', 'notifications@example.com'),
    emailSender(43, 'Support', 'support@example.com'),
]

const domainGroup: EmailIntegrationDomainGroupedType = { domain: 'example.com', integrations: senders }

const meta: Meta<typeof IntegrationEmailDomainView> = {
    title: 'Components/Integrations/IntegrationEmailDomainView',
    component: IntegrationEmailDomainView,
    args: { integration: domainGroup },
    decorators: [
        (Story) => {
            useStorybookMocks({
                get: {
                    '/api/projects/:team_id/integrations/': { results: senders },
                    '/api/environments/:team_id/integrations/': { results: senders },
                },
            })
            return <Story />
        },
    ],
}
export default meta

type Story = StoryObj<typeof IntegrationEmailDomainView>

export const Expanded: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByText('example.com'))
        await canvas.findByText('notifications@example.com', { exact: false })
    },
}
