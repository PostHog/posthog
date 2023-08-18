import { StoryFn, Meta } from '@storybook/react'
import { App } from 'scenes/App'
import { useEffect } from 'react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { PluginTab } from 'scenes/plugins/types'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

const meta: Meta = {
    title: 'Scenes-App/Apps',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
    },
}
export default meta
export const Installed: StoryFn = () => {
    useAvailableFeatures([AvailableFeature.APP_METRICS])
    useEffect(() => {
        router.actions.push(urls.projectApps(PluginTab.Installed))
    })
    return <App />
}
