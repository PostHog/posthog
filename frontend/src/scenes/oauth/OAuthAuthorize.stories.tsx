import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const multiOrgProjectsDecorator = mswDecorator({
    get: {
        '/api/oauth_application/metadata/test-client-id/': {
            id: '123',
            client_id: 'test-client-id',
            name: 'Test OAuth Application',
            description: 'This is a test OAuth application for development',
            created_at: '2023-01-01T00:00:00Z',
            updated_at: '2023-01-01T00:00:00Z',
        },
        '/api/projects/': {
            results: [
                {
                    id: 1,
                    name: 'Production',
                    organization: 'org-1',
                    api_token: 'phc_prod_token',
                },
                {
                    id: 2,
                    name: 'Staging',
                    organization: 'org-1',
                    api_token: 'phc_staging_token',
                },
                {
                    id: 3,
                    name: 'Development',
                    organization: 'org-1',
                    api_token: 'phc_dev_token',
                },
                {
                    id: 4,
                    name: 'Mobile App',
                    organization: 'org-2',
                    api_token: 'phc_mobile_token',
                },
                {
                    id: 5,
                    name: 'Web App',
                    organization: 'org-2',
                    api_token: 'phc_web_token',
                },
            ],
        },
    },
    post: {
        '/oauth/authorize/': {
            redirect_to: 'https://example.com/callback?code=test-auth-code&state=test-state',
        },
    },
})

const meta: Meta = {
    title: 'Scenes-App/OAuth/Authorize',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        testOptions: {
            waitForSelector: '.max-w-2xl',
        },
    },
    decorators: [multiOrgProjectsDecorator],
}

export default meta

export const DefaultScopes: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        const params = new URLSearchParams({
            client_id: 'test-client-id',
            redirect_uri: 'https://example.com/callback',
            response_type: 'code',
            state: 'test-state',
        })
        router.actions.push(`${urls.oauthAuthorize()}?${params.toString()}`)
    })

    return <App />
}

export const WithScopes: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        const params = new URLSearchParams({
            client_id: 'test-client-id',
            redirect_uri: 'https://app.example.com/oauth/callback',
            response_type: 'code',
            state: 'test-state',
            scope: 'experiment:read experiment:write query:read feature_flag:write',
        })
        router.actions.push(`${urls.oauthAuthorize()}?${params.toString()}`)
    })

    return <App />
}

export const RequiresOrganizationAccess: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        const params = new URLSearchParams({
            client_id: 'test-client-id',
            redirect_uri: 'https://app.example.com/oauth/callback',
            response_type: 'code',
            state: 'test-state',
            scope: 'experiment:read',
            required_access_level: 'organization',
        })
        router.actions.push(`${urls.oauthAuthorize()}?${params.toString()}`)
    })

    return <App />
}
RequiresOrganizationAccess.storyName = 'Requires organization access'

export const RequiresProjectAccess: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        const params = new URLSearchParams({
            client_id: 'test-client-id',
            redirect_uri: 'https://app.example.com/oauth/callback',
            response_type: 'code',
            state: 'test-state',
            scope: 'experiment:read',
            required_access_level: 'project',
        })
        router.actions.push(`${urls.oauthAuthorize()}?${params.toString()}`)
    })

    return <App />
}
RequiresProjectAccess.storyName = 'Requires project access'
