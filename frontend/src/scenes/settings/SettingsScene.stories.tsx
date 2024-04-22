import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

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
