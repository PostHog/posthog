import { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'

export default {
    title: 'Scenes-App/Feature Preview',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
    decorators: [],
} as Meta

export function FeaturesList(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.featurePreview())
    }, [])
    return <App />
}
