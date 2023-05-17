import { Meta, Story } from '@storybook/react'
import { App } from 'scenes/App'
import { useEffect } from 'react'
import { router } from 'kea-router'
import { mswDecorator } from '~/mocks/browser'
import { urls } from 'scenes/urls'
import { BatchExportsResponse } from './ExportsList'

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
        mswDecorator({
            get: {
                '/api/projects/:team_id/exports/': (req, res, ctx) => {
                    return res(
                        ctx.delay(1000),
                        ctx.json({
                            exports: [
                                {
                                    export_id: 1,
                                    team_id: Number.parseInt(req.params.team_id[0]),
                                    name: 'My export to S3',
                                    destination: {
                                        type: 'S3',
                                        config: {
                                            bucket: 'my-bucket',
                                            prefix: 'my-prefix',
                                            aws_access_key_id: 'my-access-key-id',
                                            aws_secret_access_key: '',
                                        },
                                    },
                                    schedule: {
                                        type: 'INTERVAL',
                                        interval: 'HOURLY',
                                    },
                                    status: 'RUNNING',
                                    created_at: '2021-09-01T00:00:00.000000Z',
                                    last_updated_at: '2021-09-01T00:00:00.000000Z',
                                },
                            ],
                        } as BatchExportsResponse)
                    )
                },
            },
        }),
    ],
} as Meta

export const Exports: Story = () => {
    useEffect(() => {
        router.actions.push(urls.exports())
    })
    return <App />
}
