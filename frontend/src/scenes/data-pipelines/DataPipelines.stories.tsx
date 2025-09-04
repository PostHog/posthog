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
import _hogFunctionDestinations from './__mocks__/hogFunctionDestinations.json'
import _hogFunctionMetrics from './__mocks__/hogFunctionMetrics.json'
import _hogFunctionMetricsTotals from './__mocks__/hogFunctionMetricsTotals.json'
import _hogFunctionTransformations from './__mocks__/hogFunctionTransformations.json'

const batchExportsRetrieveMock: MockSignature = (req, res, ctx) => {
    const batchExport = batchExports.results.find((conf) => conf.id === req.params.id)
    if (!batchExports) {
        return res(ctx.status(404))
    }
    return res(ctx.json({ ...batchExport }))
}

const hogFunctionsRetrieveMock: MockSignature = (req, res, ctx) => {
    const hogFunction =
        _hogFunctionDestinations.results.find((conf) => conf.id === req.params.id) ||
        _hogFunctionTransformations.results.find((conf) => conf.id === req.params.id)
    if (!hogFunction) {
        return res(ctx.status(404))
    }
    return res(ctx.json({ ...hogFunction }))
}

const hogFunctionListMock: MockSignature = (req, res, ctx) => {
    const type = req.url.searchParams.get('types') || req.url.searchParams.get('type')
    const results = type?.includes('transformation')
        ? _hogFunctionTransformations
        : type?.includes('destination')
          ? _hogFunctionDestinations
          : []

    return res(ctx.json(results))
}

export default {
    title: 'Scenes-App/Data Pipelines',
    decorators: [
        // mocks used by all stories in this file
        mswDecorator({
            get: {
                // Data warehouse
                '/api/environments/:team_id/external_data_sources/wizard': empty,

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
                '/api/environments/:team_id/hog_functions/': hogFunctionListMock,
                '/api/projects/:team_id/hog_functions/': hogFunctionListMock,
                '/api/environments/:team_id/hog_functions/:id': hogFunctionsRetrieveMock,
                '/api/projects/:team_id/hog_functions/:id': hogFunctionsRetrieveMock,
                '/api/environments/:team_id/hog_functions/:id/metrics': _hogFunctionMetrics,
                '/api/projects/:team_id/hog_functions/:id/metrics': _hogFunctionMetrics,
                '/api/environments/:team_id/hog_functions/:id/metrics/totals': _hogFunctionMetricsTotals,
                '/api/projects/:team_id/hog_functions/:id/metrics/totals': _hogFunctionMetricsTotals,
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

export function PipelineTransformationPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.hogFunction(_hogFunctionTransformations.results[0].id))
    }, [])
    return <App />
}

export function PipelineDestinationPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.hogFunction(_hogFunctionDestinations.results[0].id))
    }, [])
    return <App />
}

export function PipelineDestinationPageMetrics(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.hogFunction(_hogFunctionDestinations.results[0].id, 'metrics'))
    }, [])
    return <App />
}

export function PipelineDestinationPageLogs(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.hogFunction(_hogFunctionDestinations.results[0].id, 'logs'))
    }, [])
    return <App />
}
