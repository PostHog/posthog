import type { Meta, StoryObj } from '@storybook/react'

import { OAuthConnectionLogos } from './OAuthConnectionLogos'

const meta: Meta<typeof OAuthConnectionLogos> = {
    title: 'Components/OAuth connection logos',
    component: OAuthConnectionLogos,
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof OAuthConnectionLogos>

export const WithLogo: Story = {
    // Served from frontend/public, so the snapshot never reaches out to a host we do not control.
    args: { appName: 'Zapier', logoUri: '/static/services/zapier.png' },
}

export const WithoutLogo: Story = {
    args: { appName: 'Zapier', logoUri: null },
}

export const BrokenLogo: Story = {
    args: { appName: 'Zapier', logoUri: '/static/services/this-icon-does-not-exist.png' },
}
