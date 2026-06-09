import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { PostponeInvite } from './PostponeInvite'

const meta: Meta = {
    title: 'Scenes-Other/Postpone Invite',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/invite_postpone': () => [
                    200,
                    {
                        organization_name: 'PostHog',
                        target_email: 'recipient@example.com',
                        inviter_first_name: 'Alice',
                        scheduled_send_at: null,
                        expires_at: '2026-06-10T00:00:00Z',
                    },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const PostponeInviteScene: Story = {
    render: () => <PostponeInvite />,
}
