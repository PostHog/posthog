import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/react'

import { LemonCard } from '@posthog/lemon-ui'

import { browserNotificationLogic } from '../../browserNotificationLogic'
import { BrowserNotificationsSection } from './BrowserNotificationsSection'

const meta: Meta<typeof BrowserNotificationsSection> = {
    title: 'Scenes-App/Support/BrowserNotificationsSection',
    component: BrowserNotificationsSection,
    parameters: { layout: 'padded', viewMode: 'story' },
    decorators: [
        (Story) => (
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <Story />
            </LemonCard>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof BrowserNotificationsSection>

export const PermissionDenied: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('Browser notifications')
        browserNotificationLogic.actions.setEnabled(false)
        browserNotificationLogic.actions.setPermission('denied')

        const message = await canvas.findByText(/Browser notifications are blocked/)
        await waitFor(() => {
            const bounds = message.getBoundingClientRect()
            if (bounds.width <= 300 || bounds.height >= 150) {
                throw new Error('Blocked notification guidance must remain readable without collapsing into a strip')
            }
        })
    },
}

export const PermissionDeniedNarrow: Story = {
    ...PermissionDenied,
    decorators: [
        (Story) => (
            <div className="w-130 max-w-full">
                <Story />
            </div>
        ),
    ],
}

export const PermissionDefault: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('Browser notifications')
        browserNotificationLogic.actions.setEnabled(false)
        browserNotificationLogic.actions.setPermission('default')
        await canvas.findByText('Enable browser notifications')
    },
}

export const PermissionGranted: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('Browser notifications')
        browserNotificationLogic.actions.setPermission('granted')
        browserNotificationLogic.actions.setEnabled(true)
        await canvas.findByText(/Not seeing notifications/)
    },
}
