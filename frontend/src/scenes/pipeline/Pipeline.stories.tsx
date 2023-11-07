import { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { App } from 'scenes/App'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { PipelineTabs } from '~/types'
import { pipelineLogic } from './pipelineLogic'

export default {
    title: 'Scenes-App/Pipeline',
    decorators: [],
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
export function PipelineTransformationsPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTabs.Transformations))
        pipelineLogic.mount()
    }, [])
    return <App />
}
