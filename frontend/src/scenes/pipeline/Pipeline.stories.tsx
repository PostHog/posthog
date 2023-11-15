import { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { App } from 'scenes/App'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { PipelineTabs } from '~/types'
import { pipelineLogic } from './pipelineLogic'
import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

export default {
    title: 'Scenes-App/Pipeline',
    decorators: [
        // mocks used by all stories in this file
        mswDecorator({
            get: {
                'api/organizations/@current/pipeline_transformations/': {},
                'api/projects/:team_id/pipeline_transformations_configs/': {},
            },
        }),
    ],
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' }, // scene mode
} as Meta

export function PipelineLandingPage(): JSX.Element {
    // also Destinations page
    useEffect(() => {
        router.actions.push(urls.pipeline())
        pipelineLogic.mount()
    }, [])
    return <App />
}
export function PipelineFilteringPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTabs.Filters))
        pipelineLogic.mount()
    }, [])
    return <App />
}

export function PipelineTransformationsPageEmpty(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTabs.Transformations))
        pipelineLogic.mount()
    }, [])
    return <App />
}

export function PipelineTransformationsPage(): JSX.Element {
    useStorybookMocks({
        get: {
            'api/organizations/@current/pipeline_transformations/': require('./__mocks__/plugins.json'),
            'api/projects/:team_id/pipeline_transformations_configs/': require('./__mocks__/transformationPluginConfigs.json'),
        },
    })
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTabs.Transformations))
        pipelineLogic.mount()
    }, [])
    return <App />
}
