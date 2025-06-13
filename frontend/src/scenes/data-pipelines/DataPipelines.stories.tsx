import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { MockSignature } from '~/mocks/utils'
import { AvailableFeature } from '~/types'

import batchExports from './__mocks__/batchExports.json'
import empty from './__mocks__/empty.json'

const batchExportsRetrieveMock: MockSignature = (req, res, ctx) => {
    const batchExport = batchExports.results.find((conf) => conf.id === req.params.id)
    if (!batchExports) {
        return res(ctx.status(404))
    }
    return res(ctx.json({ ...batchExport }))
}

export default {
    title: 'Scenes-App/Data Pipelines',
    decorators: [
        // mocks used by all stories in this file
        mswDecorator({
            get: {
                // Legacy pipeline parts
                '/api/projects/:team_id/pipeline_destination_configs/': empty,
                '/api/organizations/:organization_id/pipeline_destinations/': empty,
                '/api/projects/:team_id/pipeline_frontend_apps_configs/': empty,
                '/api/organizations/:organization_id/pipeline_frontend_apps/': empty,
                '/api/projects/:team_id/pipeline_transformation_configs/': empty,
                '/api/organizations/:organization_id/pipeline_transformations/': empty,

                // Batch exports
                '/api/projects/:team_id/batch_exports/': batchExports,
                '/api/projects/:team_id/batch_exports/:id': batchExportsRetrieveMock,
                '/api/environments/:team_id/batch_exports/': batchExports,
                '/api/environments/:team_id/batch_exports/:id': batchExportsRetrieveMock,
                '/api/organizations/:organization_id/batch_exports/': batchExports,
                '/api/projects/:team_id/integrations/': empty,
                '/api/environments/:team_id/integrations/': empty,

                // Hog functions
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        mockDate: '2023-02-18',
    }, // scene mode
} as Meta

export function PipelineOverviewPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.dataPipelines('overview'))
    }, [])
    return <App />
}

export function PipelineTransformationsPageEmpty(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/pipeline_transformation_configs/': empty,
        },
    })
    useEffect(() => {
        router.actions.push(urls.dataPipelines('transformations'))
    }, [])
    return <App />
}

export function PipelineTransformationsPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.dataPipelines('transformations'))
    }, [])
    return <App />
}

export function PipelineDestinationsPage(): JSX.Element {
    useAvailableFeatures([AvailableFeature.DATA_PIPELINES])
    useEffect(() => {
        router.actions.push(urls.dataPipelines('destinations'))
    }, [])
    return <App />
}

export function PipelineDestinationsPageWithoutPipelines(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.dataPipelines('destinations'))
    }, [])
    return <App />
}

export function PipelineSiteAppsPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.dataPipelines('site_apps'))
    }, [])
    return <App />
}
