import React, { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'

export default {
    title: 'Scenes/FeatureFlags',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' }, // scene mode
} as Meta

export function NewFeatureFlag(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.featureFlag('new'))
    }, [])
    return <App />
}

export function FeatureFlagsList(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.featureFlags())
    }, [])
    return <App />
}
