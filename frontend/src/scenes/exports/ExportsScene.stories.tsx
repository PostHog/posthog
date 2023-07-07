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
    decorators: [
        mswDecorator(
            createExportServiceHandlers({
                1: {
                    id: '1',
                    team_id: 1,
                    name: 'S3',
                    destination: {
                        type: 'S3',
                        config: {
                            bucket_name: 'my-bucket',
                            region: 'us-east-1',
                            prefix: 'my-prefix',
                            aws_access_key_id: 'my-access-key-id',
                            aws_secret_access_key: '',
                        },
                    },
                    start_at: null,
                    end_at: null,
                    interval: 'hour',
                    status: 'RUNNING',
                    paused: false,
                    created_at: '2021-09-01T00:00:00.000000Z',
                    last_updated_at: '2021-09-01T00:00:00.000000Z',
                },
            }).handlers
        ),
    ],
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
