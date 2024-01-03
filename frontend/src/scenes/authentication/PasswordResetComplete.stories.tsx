// PasswordResetComplete.stories.tsx
import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { urls } from 'scenes/urls'

import { useStorybookMocks } from '~/mocks/browser'

import { PasswordResetComplete } from './PasswordResetComplete'

// some metadata and optional parameters
const meta: Meta = {
    title: 'Scenes-Other/Password Reset Complete',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta
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
