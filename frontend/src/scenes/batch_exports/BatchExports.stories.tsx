import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

import { createExportServiceHandlers } from './__mocks__/api-mocks'

export default {
    title: 'Scenes-App/BatchExports',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        testOptions: {
            excludeNavigationFromSnapshot: true,
            waitForLoadersToDisappear: true,
        },
        mockDate: '2023-02-01',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator(
            createExportServiceHandlers({
                1: {
                    id: '1',
                    team_id: 1,
                    name: 'My S3 Exporter',
                    destination: {
                        type: 'S3',
                        config: {
                            bucket_name: 'my-bucket',
                            region: 'us-east-1',
                            prefix: 'my-prefix',
                            aws_access_key_id: 'my-access-key-id',
                            aws_secret_access_key: '',
                            compression: null,
                            exclude_events: [],
                            include_events: [],
                            encryption: null,
                            kms_key_id: null,
                        },
                    },
                    start_at: null,
                    end_at: null,
                    interval: 'hour',
                    paused: false,
                    created_at: '2021-09-01T00:00:00.000000Z',
                    latest_runs: [
                        {
                            id: '4',
                            status: 'Running',
                            created_at: '2023-01-01T12:00:00Z' as any,
                            data_interval_start: '2023-01-01T05:00:00Z' as any,
                            data_interval_end: '2023-01-01T06:00:00Z' as any,
                        },
                        {
                            id: '3',
                            status: 'Failed',
                            created_at: '2023-01-01T12:00:00Z' as any,
                            data_interval_start: '2023-01-01T03:00:00Z' as any,
                            data_interval_end: '2023-01-01T04:00:00Z' as any,
                        },
                        {
                            id: '2',
                            status: 'Completed',
                            created_at: '2023-01-01T12:00:00Z' as any,
                            data_interval_start: '2023-01-01T01:00:00Z' as any,
                            data_interval_end: '2023-01-01T02:00:00Z' as any,
                        },
                        {
                            id: '1',
                            status: 'Completed',
                            created_at: '2023-01-01T12:00:00Z' as any,
                            data_interval_start: '2023-01-01T00:00:00Z' as any,
                            data_interval_end: '2023-01-01T01:00:00Z' as any,
                        },
                    ],
                },
            }).handlers
        ),
    ],
} as Meta

export const Exports: StoryFn = () => {
    useAvailableFeatures([AvailableFeature.DATA_PIPELINES])
    useEffect(() => {
        router.actions.push(urls.batchExports())
    })
    return <App />
}
Exports.parameters = {
    testOptions: {
        waitForSelector: '.BatchExportRunIcon',
    },
}

export const CreateExport: StoryFn = () => {
    useAvailableFeatures([AvailableFeature.DATA_PIPELINES])
    useEffect(() => {
        router.actions.push(urls.batchExportNew())
    })
    return <App />
}

export const ViewExport: StoryFn = () => {
    useAvailableFeatures([AvailableFeature.DATA_PIPELINES])
    useEffect(() => {
        router.actions.push(urls.batchExport('1'))
    })
    return <App />
}
ViewExport.parameters = {
    testOptions: {
        waitForSelector: '.LemonTable',
    },
}
