import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { MOCK_DEFAULT_USER } from 'lib/api.mock'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { AvailableFeature, UserType } from '~/types'

const meta: Meta = {
    title: 'Scenes-Other/Settings',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
                '/api/projects/:id/integrations': { results: [] },
            },
        }),
    ],
}
export default meta

export const SettingsProject: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.settings('project'))
    }, [])
    return <App />
}
SettingsProject.parameters = {
    testOptions: { waitForSelector: '.Settings__sections button' },
}

export const SettingsProjectWithReplayFeatures: StoryFn = () => {
    useAvailableFeatures([
        AvailableFeature.SESSION_REPLAY_SAMPLING,
        AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM,
        AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING,
    ])
    useEffect(() => {
        router.actions.push(urls.settings('project'))
    }, [])
    return <App />
}
SettingsProjectWithReplayFeatures.parameters = {
    testOptions: { waitForSelector: '.Settings__sections button' },
}

export const SettingsUser: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.settings('user'))
    }, [])
    return <App />
}
SettingsUser.parameters = {
    testOptions: { waitForSelector: '.Settings__sections button' },
}

export const SettingsOrganization: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.settings('organization'))
    }, [])
    return <App />
}
SettingsOrganization.parameters = {
    testOptions: { waitForSelector: '.Settings__sections button' },
}

export const SettingsSessionTimeout: StoryFn = () => {
    const timedOutSessionUser: UserType = {
        ...MOCK_DEFAULT_USER,
        sensitive_session_expires_at: '2023-05-25T00:00:00Z',
        has_social_auth: true,
    }
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: true,
                realm: 'cloud',
                available_social_auth_providers: { github: true, gitlab: true, 'google-oauth2': true, saml: false },
            },
            '/api/users/@me': timedOutSessionUser,
        },
    })

    useEffect(() => {
        router.actions.push(urls.settings('project'))
    }, [])

    return <App />
}
SettingsSessionTimeout.parameters = {
    testOptions: { waitForSelector: '.Settings__sections button' },
}
