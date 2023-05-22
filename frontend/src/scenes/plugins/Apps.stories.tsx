import { Meta, Story } from '@storybook/react'
import { App } from 'scenes/App'
import { useEffect } from 'react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { PluginTab } from 'scenes/plugins/types'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

export default {
    title: 'Scenes-App/Apps',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
    },
} as Meta

export const Installed: Story = () => {
    useAvailableFeatures([AvailableFeature.APP_METRICS])
    useEffect(() => {
        router.actions.push(urls.projectApps(PluginTab.Installed))
    })
    return <App />
}
