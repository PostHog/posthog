import React, { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { mswDecorator } from '~/mocks/browser'
import { App } from 'scenes/App'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export default {
    title: 'Scenes/Dashboard',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/1/dashboards/': require('./__mocks__/dashboards.json'),
                '/api/projects/1/dashboards/1/': require('./__mocks__/dashboard1.json'),
                '/api/projects/1/dashboards/1/collaborators/': [],
            },
        }),
    ],
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
} as Meta

export const Default = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.dashboard(1))
    }, [])
    return <App />
}
