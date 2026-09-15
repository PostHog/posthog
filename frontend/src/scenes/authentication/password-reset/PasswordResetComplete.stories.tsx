// PasswordResetComplete.stories.tsx
import { Meta, StoryObj } from '@storybook/react'
import { HttpResponse, delay } from 'msw'

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

type Story = StoryObj<{}>
export const InvalidLink: Story = {}

export const ExpiredLink: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/reset/user-uuid-3f32/': () =>
                    HttpResponse.json(
                        {
                            type: 'validation_error',
                            code: 'expired_token',
                            detail: 'This reset link expired. Links work for 24 hours. Request a new one to set your password.',
                            attr: 'token',
                        },
                        { status: 400 }
                    ),
            },
        }),
    ],
}

export const AlreadyUsedLink: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/reset/user-uuid-3f32/': () =>
                    HttpResponse.json(
                        {
                            type: 'validation_error',
                            code: 'password_already_reset',
                            detail: 'You already used this link to change your password. Try logging in with your new password.',
                            attr: 'token',
                        },
                        { status: 400 }
                    ),
            },
        }),
    ],
}

export const Default: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/reset/user-uuid-3f32/': { success: true } },
            post: {
                '/api/reset/user-uuid-3f32/': async () => {
                    await delay(1000)
                    return new HttpResponse(null, { status: 200 })
                },
            },
        }),
    ],
}
