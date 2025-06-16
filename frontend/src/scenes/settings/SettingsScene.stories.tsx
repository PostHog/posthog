import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'
import { FEATURE_FLAGS } from 'lib/constants'
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
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING],
        testOptions: { waitForSelector: '.Settings__sections a' },
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
            patch: {
                '/api/projects/:id': async (req, res, ctx) => {
                    // bounce the setting back as is
                    const newTeamSettings = { ...MOCK_DEFAULT_TEAM, ...(await req.json()) }
                    return res(ctx.json(newTeamSettings))
                },
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

export const SettingsUser: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.settings('user'))
    }, [])
    return <App />
}

export const SettingsOrganization: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.settings('organization'))
    }, [])
    return <App />
}

function TimeSensitiveSettings(props: {
    has_password?: boolean
    saml_available?: boolean
    sso_enforcement?: string
}): JSX.Element {
    const timedOutSessionUser: UserType = {
        ...MOCK_DEFAULT_USER,
        sensitive_session_expires_at: '2023-05-25T00:00:00Z',
        has_password: props.has_password ?? false,
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
        post: {
            '/api/login/precheck': {
                sso_enforcement: props.sso_enforcement,
                saml_available: props.saml_available,
            },
        },
    })

    useEffect(() => {
        router.actions.push(urls.settings('project'))
    }, [])

    return <App />
}

export const SettingsSessionTimeoutAllOptions: StoryFn = () => {
    return <TimeSensitiveSettings has_password saml_available />
}

export const SettingsSessionTimeoutPasswordOnly: StoryFn = () => {
    return <TimeSensitiveSettings has_password />
}

export const SettingsSessionTimeoutSsoOnly: StoryFn = () => {
    return <TimeSensitiveSettings />
}

export const SettingsSessionTimeoutSsoEnforcedGithub: StoryFn = () => {
    return <TimeSensitiveSettings sso_enforcement="github" />
}

export const SettingsSessionTimeoutSsoEnforcedGoogle: StoryFn = () => {
    return <TimeSensitiveSettings sso_enforcement="google-oauth2" />
}

export const SettingsSessionTimeoutSsoEnforcedSaml: StoryFn = () => {
    return <TimeSensitiveSettings sso_enforcement="saml" />
}
