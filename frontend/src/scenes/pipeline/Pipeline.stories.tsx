import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { MockSignature } from '~/mocks/utils'
import { AvailableFeature, PipelineNodeTab, PipelineStage, PipelineTab } from '~/types'

import batchExports from './__mocks__/batchExports.json'
import empty from './__mocks__/empty.json'
import pluginConfigs from './__mocks__/pluginConfigs.json'
import plugins from './__mocks__/plugins.json'
import { appsManagementLogic } from './appsManagementLogic'
import { pipelineNodeMetricsLogic } from './pipelineNodeMetricsLogic'

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
    title: 'Scenes-App/Pipeline',
    decorators: [
        // mocks used by all stories in this file
        mswDecorator({
            get: {
                '/api/projects/:team_id/batch_exports/': batchExports,
                '/api/projects/:team_id/batch_exports/:id': batchExportsRetrieveMock,
                '/api/organizations/:organization_id/batch_exports/': batchExports,
                '/api/organizations/:organization_id/plugins/': plugins,
                '/api/organizations/:organization_id/plugins/repository': [],
                '/api/organizations/:organization_id/plugins/unused': [],
                '/api/organizations/:organization_id/plugins/:id': pluginRetrieveMock,
                '/api/projects/:team_id/plugin_configs/': pluginConfigs,
                '/api/projects/:team_id/plugin_configs/:id': pluginConfigRetrieveMock,
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
        featureFlags: [FEATURE_FLAGS.PIPELINE_UI],
    }, // scene mode
} as Meta

const eventSequenceTimerPluginId = plugins.results.find((plugin) => plugin.name === 'Event Sequence Timer Plugin')!.id
const eventSequenceTimerPluginConfigId = pluginConfigs.results.find(
    (conf) => conf.plugin === eventSequenceTimerPluginId
)!.id
const geoIpConfigId = pluginConfigs.results.find(
    (conf) => conf.plugin === plugins.results.find((plugin) => plugin.name === 'GeoIP')!.id
)!.id

export function PipelineLandingPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline())
    }, [])
    return <App />
}

export function PipelineOverviewPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.Overview))
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
        router.actions.push(urls.pipeline(PipelineTab.Transformations))
    }, [])
    return <App />
}

export function PipelineTransformationsPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.Transformations))
    }, [])
    return <App />
}

export function PipelineDestinationsPage(): JSX.Element {
    useAvailableFeatures([AvailableFeature.DATA_PIPELINES])
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.Destinations))
    }, [])
    return <App />
}

export function PipelineDestinationsPageWithoutPipelines(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.Destinations))
    }, [])
    return <App />
}

export function PipelineSiteAppsPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.SiteApps))
    }, [])
    return <App />
}

export function PipelineLegacySourcesPage(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/organizations/:organization_id/pipeline_import_apps/': plugins,
            '/api/projects/:team_id/pipeline_import_apps_configs/': pluginConfigs,
            '/api/projects/:team_id/pipeline_import_apps_configs/:id': pluginConfigRetrieveMock,
        },
    })
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.ImportApps))
    }, [])
    return <App />
}

export function PipelineLandingPageIffLegacySources(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/organizations/:organization_id/pipeline_import_apps/': plugins,
            '/api/projects/:team_id/pipeline_import_apps_configs/': pluginConfigs,
            '/api/projects/:team_id/pipeline_import_apps_configs/:id': pluginConfigRetrieveMock,
        },
    })
    useEffect(() => {
        router.actions.push(urls.pipeline())
    }, [])
    return <App />
}

export function PipelineNodeNewTransformation(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipelineNodeNew(PipelineStage.Transformation))
    }, [])
    return <App />
}

export function PipelineNodeNewDestination(): JSX.Element {
    useAvailableFeatures([AvailableFeature.DATA_PIPELINES])
    useEffect(() => {
        router.actions.push(urls.pipelineNodeNew(PipelineStage.Destination))
    }, [])
    return <App />
}

export function PipelineNodeNewDestinationWithoutDataPipelines(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipelineNodeNew(PipelineStage.Destination))
    }, [])
    return <App />
}

export function PipelineNodeNewSequenceTimer(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipelineNodeNew(PipelineStage.Transformation, eventSequenceTimerPluginId))
    }, [])
    return <App />
}

export function PipelineNodeNewBigQuery(): JSX.Element {
    useAvailableFeatures([AvailableFeature.DATA_PIPELINES])
    useEffect(() => {
        router.actions.push(urls.pipelineNodeNew(PipelineStage.Destination, 'BigQuery'))
    }, [])
    return <App />
}

export function PipelineNodeNewBigQueryWithoutPipelines(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipelineNodeNew(PipelineStage.Destination, 'BigQuery'))
    }, [])
    return <App />
}

export function PipelineNodeEditConfiguration(): JSX.Element {
    useEffect(() => {
        router.actions.push(
            urls.pipelineNode(
                PipelineStage.Destination,
                eventSequenceTimerPluginConfigId,
                PipelineNodeTab.Configuration
            )
        )
    }, [])
    return <App />
}

export function PipelineNodeEditConfigurationStatelessPlugin(): JSX.Element {
    useEffect(() => {
        router.actions.push(
            urls.pipelineNode(PipelineStage.Transformation, geoIpConfigId, PipelineNodeTab.Configuration)
        )
    }, [])
    return <App />
}

export function PipelineNodeConfiguration404(): JSX.Element {
    useEffect(() => {
        router.actions.push(
            urls.pipelineNode(PipelineStage.Transformation, 4239084923809, PipelineNodeTab.Configuration)
        )
    }, [])
    return <App />
}

export function PipelineNodeMetrics(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipelineNode(PipelineStage.Transformation, geoIpConfigId, PipelineNodeTab.Metrics))
        pipelineNodeMetricsLogic({ id: geoIpConfigId }).mount()
    }, [])
    return <App />
}

export function PipelineNodeMetricsErrorModal(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipelineNode(PipelineStage.Transformation, geoIpConfigId, PipelineNodeTab.Metrics))
        const logic = pipelineNodeMetricsLogic({ id: geoIpConfigId })
        logic.mount()
        logic.actions.openErrorDetailsModal('Error')
    }, [])
    return <App />
}

export function PipelineNodeLogs(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/plugin_configs/:plugin_config_id/logs': require('./__mocks__/pluginLogs.json'),
        },
    })
    useEffect(() => {
        router.actions.push(urls.pipelineNode(PipelineStage.Transformation, geoIpConfigId, PipelineNodeTab.Logs))
    }, [])
    return <App />
}

export function PipelineNodeLogsBatchExport(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/batch_exports/:export_id/logs': require('./__mocks__/batchExportLogs.json'),
        },
    })
    useEffect(() => {
        router.actions.push(
            urls.pipelineNode(PipelineStage.Destination, batchExports.results[0].id, PipelineNodeTab.Logs)
        )
    }, [])
    return <App />
}

export function PipelineNodesManagementPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.AppsManagement))
        appsManagementLogic.mount()
    }, [])
    return <App />
}
