import { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { App } from 'scenes/App'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export default {
    title: 'Scenes-App/Pipeline',
    decorators: [],
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' }, // scene mode
} as Meta

export function PipelineLandingPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline())
    }, [])
    return <App />
}
