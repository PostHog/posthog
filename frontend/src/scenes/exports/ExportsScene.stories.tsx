import { Meta, Story } from '@storybook/react'
import { App } from 'scenes/App'
import { useEffect } from 'react'
import { router } from 'kea-router'
import { mswDecorator } from '~/mocks/browser'
import { urls } from 'scenes/urls'
import { createExportServiceHandlers } from './api-mocks'

export default {
    title: 'Scenes-App/Exports',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
    },
    decorators: [mswDecorator(createExportServiceHandlers().handlers)],
} as Meta

export const Exports: Story = () => {
    useEffect(() => {
        router.actions.push(urls.exports())
    })
    return <App />
}

export const CreateExport: Story = () => {
    useEffect(() => {
        router.actions.push(urls.createExport())
    })
    return <App />
}
