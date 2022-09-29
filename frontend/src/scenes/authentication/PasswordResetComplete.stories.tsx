// PasswordResetComplete.stories.tsx
import { Meta } from '@storybook/react'
import { PasswordResetComplete } from './PasswordResetComplete'
import React, { useEffect } from 'react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { useStorybookMocks } from '~/mocks/browser'

// some metadata and optional parameters
export default {
    title: 'Scenes-Other/Password Reset Complete',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
} as Meta

// export more stories with different state
export const Default = (): JSX.Element => {
    useStorybookMocks({
        get: { '/api/reset/user-uuid-3f32/': { success: true } },
        post: { '/api/reset/user-uuid-3f32/': (_, __, ctx) => [ctx.delay(1000), ctx.status(200)] },
    })
    useEffect(() => {
        router.actions.push(urls.passwordResetComplete('user-uuid-3f32', 'token'))
    }, [])
    return <PasswordResetComplete />
}
export const InvalidLink = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.passwordResetComplete('user-uuid-3f32', 'token'))
    }, [])
    return <PasswordResetComplete />
}
