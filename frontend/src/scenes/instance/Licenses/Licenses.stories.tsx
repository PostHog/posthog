import React, { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { App } from 'scenes/App'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export default {
    title: 'Scenes-App/Licenses',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
} as Meta

export const Licenses = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.instanceLicenses())
    }, [])
    return <App />
}
