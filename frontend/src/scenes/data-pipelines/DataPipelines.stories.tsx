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
import pluginConfigs from './__mocks__/pluginConfigs.json'
import plugins from './__mocks__/plugins.json'

const pluginRetrieveMock: MockSignature = (req, res, ctx) => {
    const plugin = plugins.results.find((conf) => conf.id === Number(req.params.id))
    if (!plugin) {
        return res(ctx.status(404))
    }
    return res(ctx.json({ ...plugin }))
}

const pluginConfigRetrieveMock: MockSignature = (req, res, ctx) => {
    const pluginConfig = pluginConfigs.results.find((conf) => conf.id === Number(req.params.id))
    if (!pluginConfig) {
        return res(ctx.status(404))
    }
    const plugin = plugins.results.find((plugin) => plugin.id === pluginConfig.plugin)
    return res(ctx.json({ ...pluginConfig, plugin_info: plugin }))
}

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
                '/api/projects/:team_id/batch_exports/': batchExports,
                '/api/projects/:team_id/batch_exports/:id': batchExportsRetrieveMock,
                '/api/environments/:team_id/batch_exports/': batchExports,
                '/api/environments/:team_id/batch_exports/:id': batchExportsRetrieveMock,
                '/api/organizations/:organization_id/batch_exports/': batchExports,
                '/api/organizations/:organization_id/plugins/': plugins,
                '/api/organizations/:organization_id/plugins/repository': [],
                '/api/organizations/:organization_id/plugins/unused': [],
                '/api/organizations/:organization_id/plugins/:id': pluginRetrieveMock,
                '/api/environments/:team_id/plugin_configs/': pluginConfigs,
                '/api/environments/:team_id/plugin_configs/:id': pluginConfigRetrieveMock,
                // TODO: Differentiate between transformation and destination mocks for nicer mocks
                '/api/organizations/:organization_id/pipeline_transformations/': plugins,
                '/api/projects/:team_id/pipeline_transformation_configs/': pluginConfigs,
                '/api/projects/:team_id/pipeline_transformation_configs/:id': pluginConfigRetrieveMock,
                '/api/organizations/:organization_id/pipeline_destinations/': plugins,
                '/api/projects/:team_id/pipeline_destination_configs/': pluginConfigs,
                '/api/projects/:team_id/pipeline_destination_configs/:id': pluginConfigRetrieveMock,
                '/api/organizations/:organization_id/pipeline_frontend_apps/': plugins,
                '/api/projects/:team_id/pipeline_frontend_apps_configs/': pluginConfigs,
                '/api/projects/:team_id/pipeline_frontend_apps_configs/:id': pluginConfigRetrieveMock,
                '/api/organizations/:organization_id/pipeline_import_apps/': empty,
                '/api/projects/:team_id/pipeline_import_apps_configs/': empty,
                '/api/projects/:team_id/integrations/': empty,
                '/api/environments/:team_id/integrations/': empty,
                '/api/projects/:team_id/app_metrics/:plugin_config_id?date_from=-7d': require('./__mocks__/pluginMetrics.json'),
                '/api/projects/:team_id/app_metrics/:plugin_config_id/error_details?error_type=Error': require('./__mocks__/pluginErrorDetails.json'),
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
