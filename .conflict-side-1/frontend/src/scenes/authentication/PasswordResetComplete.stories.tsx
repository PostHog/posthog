// PasswordResetComplete.stories.tsx
import { Meta, StoryObj } from '@storybook/react'

import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { PasswordResetComplete } from './PasswordResetComplete'

// some metadata and optional parameters
const meta: Meta = {
    component: PasswordResetComplete,
    title: 'Scenes-Other/Password Reset Complete',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.passwordResetComplete('user-uuid-3f32', 'token'),
    },
}
export default meta

type Story = StoryObj<typeof meta>
export const InvalidLink: Story = {}

export const Default: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/reset/user-uuid-3f32/': { success: true } },
            post: { '/api/reset/user-uuid-3f32/': (_, __, ctx) => [ctx.delay(1000), ctx.status(200)] },
        }),
    ],
}
