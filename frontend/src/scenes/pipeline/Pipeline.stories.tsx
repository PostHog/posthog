import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { MockSignature } from '~/mocks/utils'
import { PipelineNodeTab, PipelineStage, PipelineTab } from '~/types'

import batchExports from './__mocks__/batchExports.json'
import pluginConfigs from './__mocks__/pluginConfigs.json'
import plugins from './__mocks__/plugins.json'
import { appsManagementLogic } from './appsManagementLogic'
import { pipelineLogic } from './pipelineLogic'
import { pipelineNodeMetricsLogic } from './pipelineNodeMetricsLogic'

const pluginConfigRetrieveMock: MockSignature = (req, res, ctx) => {
    const pluginConfig = pluginConfigs.results.find((conf) => conf.id === Number(req.params.id))
    if (!pluginConfig) {
        return res(ctx.status(404))
    }
    const plugin = plugins.results.find((plugin) => plugin.id === pluginConfig.plugin)
    return res(ctx.json({ ...pluginConfig, plugin_info: plugin }))
}

export default {
    title: 'Scenes-App/Pipeline',
    decorators: [
        // mocks used by all stories in this file
        mswDecorator({
            get: {
                '/api/projects/:team_id/batch_exports/': batchExports,
                '/api/organizations/:organization_id/batch_exports/': batchExports,
                '/api/organizations/:organization_id/plugins/': plugins,
                '/api/projects/:team_id/plugin_configs/': pluginConfigs,
                '/api/projects/:team_id/plugin_configs/:id': pluginConfigRetrieveMock,
                // TODO: Differentiate between transformation and destination mocks for nicer mocks
                '/api/organizations/:organization_id/pipeline_transformations/': plugins,
                '/api/projects/:team_id/pipeline_transformation_configs/': pluginConfigs,
                '/api/projects/:team_id/pipeline_transformation_configs/:id': pluginConfigRetrieveMock,
                '/api/organizations/:organization_id/pipeline_destinations/': plugins,
                '/api/projects/:team_id/pipeline_destination_configs/': pluginConfigs,
                '/api/projects/:team_id/pipeline_destination_configs/:id': pluginConfigRetrieveMock,

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

const eventSequenceTimerPluginConfigId = pluginConfigs.results.find(
    (conf) => conf.plugin === plugins.results.find((plugin) => plugin.name === 'Event Sequence Timer Plugin')!.id
)!.id
const geoIpConfigId = pluginConfigs.results.find(
    (conf) => conf.plugin === plugins.results.find((plugin) => plugin.name === 'GeoIP')!.id
)!.id

export function PipelineLandingPage(): JSX.Element {
    // also Destinations page
    useEffect(() => {
        router.actions.push(urls.pipeline())
        pipelineLogic.mount()
    }, [])
    return <App />
}

export function PipelineOverviewPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.Overview))
        pipelineLogic.mount()
    }, [])
    return <App />
}

export function PipelineFilteringPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.Filters))
        pipelineLogic.mount()
    }, [])
    return <App />
}

export function PipelineTransformationsPageEmpty(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.Transformations))
        pipelineLogic.mount()
    }, [])
    return <App />
}

export function PipelineTransformationsPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.Transformations))
        pipelineLogic.mount()
    }, [])
    return <App />
}

export function PipelineDestinationsPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.Destinations))
        pipelineLogic.mount()
    }, [])
    return <App />
}

export function PipelineNodeConfiguration(): JSX.Element {
    useEffect(() => {
        router.actions.push(
            urls.pipelineNode(
                PipelineStage.Transformation,
                eventSequenceTimerPluginConfigId,
                PipelineNodeTab.Configuration
            )
        )
    }, [])
    return <App />
}

export function PipelineNodeConfigurationEmpty(): JSX.Element {
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
        pipelineNodeMetricsLogic({ pluginConfigId: geoIpConfigId }).mount()
    }, [])
    return <App />
}

export function PipelineNodeMetricsErrorModal(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipelineNode(PipelineStage.Transformation, geoIpConfigId, PipelineNodeTab.Metrics))
        const logic = pipelineNodeMetricsLogic({ pluginConfigId: geoIpConfigId })
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
            urls.pipelineNode(PipelineStage.Transformation, batchExports.results[0].id, PipelineNodeTab.Logs)
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
