import React, { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { FeatureFlag } from './FeatureFlag'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export default {
    title: 'Scenes/FeatureFlags',
    decorators: [
        // mocks used by all stories in this file
        mswDecorator({
            // get: {
            //     '/api/projects/1/dashboards/': require('./__mocks__/dashboards.json'),
            //     '/api/projects/1/dashboards/1/': require('./__mocks__/dashboard1.json'),
            //     '/api/projects/1/dashboards/1/collaborators/': [],
            // },
        }),
    ],
    // NB! These `parameters` only apply for Scene stories.
    parameters: { options: { showPanel: false }, viewMode: 'canvas' }, // scene mode
} as Meta

export function FeatureFlags(): JSX.Element {
    // mocks used only in this story
    useStorybookMocks({
        // get: { '/api/projects/dashboard2/': { success: true } },
    })
    useEffect(() => {
        // change the URL
        router.actions.push(urls.dashboard(1))
        // call various other actions to set the initial state
        dashboardModel.actions.doSomething()
    }, [])
    return <FeatureFlag id={'1'} />
}
