import { Decorator, Meta, StoryObj } from '@storybook/react'
import { useEffect, useRef } from 'react'

import type { AppContext, ToolbarOAuthErrorContext } from '~/types'

import { ToolbarOAuthError } from './ToolbarOAuthError'

// Every story shares one app context, so put back the value the story replaced when it unmounts.
function withToolbarOAuthError(error: ToolbarOAuthErrorContext): Decorator {
    return function ToolbarOAuthErrorDecorator(Story): JSX.Element {
        const appContext = (window as unknown as { POSTHOG_APP_CONTEXT: AppContext }).POSTHOG_APP_CONTEXT
        const original = useRef<{ value: AppContext['toolbar_oauth_error'] }>()
        if (!original.current) {
            original.current = { value: appContext.toolbar_oauth_error }
            appContext.toolbar_oauth_error = error
        }

        useEffect(
            () => () => {
                appContext.toolbar_oauth_error = original.current?.value
            },
            [appContext]
        )

        return <Story />
    }
}

const meta: Meta = {
    title: 'Scenes-Other/Authentication/Toolbar sign-in error',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        testOptions: { waitForSelector: '[data-attr="toolbar-oauth-error-go-back"]' },
    },
    render: () => <ToolbarOAuthError />,
}

export default meta

type Story = StoryObj<{}>

export const DomainNotAuthorized: Story = {
    decorators: [
        withToolbarOAuthError({
            title: 'Domain not authorized',
            message:
                "The toolbar cannot authenticate on this domain because it is not in your project's authorized URLs.",
            detail: "The hostname shop.example.com needs to be added to your project's authorized URLs before the toolbar can be used on this site.",
            links_to_authorized_urls: true,
        }),
    ],
    parameters: { pageUrl: '/toolbar_oauth/authorize/?redirect=https%3A%2F%2Fshop.example.com%2F' },
}

export const SignInExpired: Story = {
    decorators: [
        withToolbarOAuthError({
            title: 'This toolbar sign-in expired',
            message: 'Open the toolbar from your site again to start a new sign-in.',
            detail: null,
            links_to_authorized_urls: false,
        }),
    ],
    parameters: { pageUrl: '/toolbar_oauth/callback?code=example-code&state=example-state' },
}
