import { Meta, StoryObj } from '@storybook/react'

import { IntegrationAccessNotice } from './IntegrationAccessNotice'

const meta: Meta<typeof IntegrationAccessNotice> = {
    title: 'Components/Integrations/Access notice',
    component: IntegrationAccessNotice,
}
export default meta

type Story = StoryObj<typeof IntegrationAccessNotice>

export const GoogleAds: Story = { args: { kind: 'google-ads' } }
