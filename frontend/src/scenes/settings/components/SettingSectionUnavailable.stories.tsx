import type { Meta, StoryObj } from '@storybook/react'

import { SettingSectionUnavailable } from './SettingSectionUnavailable'

type Story = StoryObj<typeof SettingSectionUnavailable>

const meta: Meta<typeof SettingSectionUnavailable> = {
    title: 'Scenes-App/Settings/SettingSectionUnavailable',
    component: SettingSectionUnavailable,
    parameters: { layout: 'fullscreen' },
}
export default meta

export const NotEnabled: Story = {
    args: {
        section: {
            id: 'organization-oauth-apps',
            title: 'OAuth applications',
            reason: 'not-enabled',
            fallback: { sectionId: 'organization-details', label: 'Go to organization settings' },
        },
    },
}

export const AdminOnly: Story = {
    args: {
        section: {
            id: 'organization-oauth-apps',
            title: 'OAuth applications',
            reason: 'admin-only',
            fallback: { sectionId: 'organization-details', label: 'Go to organization settings' },
        },
    },
}
