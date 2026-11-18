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
            id: 'organization-access-resolution',
            title: 'Access resolution preview',
            reason: 'not-enabled',
            fallback: { sectionId: 'organization-roles', label: 'Go to access control settings' },
        },
    },
}

export const AdminOnly: Story = {
    args: {
        section: {
            id: 'organization-access-resolution',
            title: 'Access resolution preview',
            reason: 'admin-only',
            fallback: { sectionId: 'organization-roles', label: 'Go to access control settings' },
        },
    },
}
