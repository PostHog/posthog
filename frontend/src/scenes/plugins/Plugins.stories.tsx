import { Meta, Story } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

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
export const Installed: Story = () => {
    useAvailableFeatures([AvailableFeature.APP_METRICS])
    useEffect(() => {
        router.actions.push(urls.projectApps())
    })
    return <App />
}
