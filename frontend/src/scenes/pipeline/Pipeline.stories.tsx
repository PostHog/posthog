import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { PipelineNodeTab, PipelineStage, PipelineTab } from '~/types'

import batchExports from './__mocks__/batchExports.json'
import pluginConfigs from './__mocks__/pluginConfigs.json'
import plugins from './__mocks__/plugins.json'
import { appsManagementLogic } from './appsManagementLogic'
import { pipelineLogic } from './pipelineLogic'
import { pipelineNodeMetricsLogic } from './pipelineNodeMetricsLogic'

export default {
    title: 'Scenes-App/Pipeline',
    decorators: [
        // mocks used by all stories in this file
        mswDecorator({
            get: {
                '/api/projects/:team_id/batch_exports/': batchExports,
                '/api/organizations/:organization_id/batch_exports/': batchExports,
                '/api/organizations/@current/plugins/': plugins,
                '/api/organizations/@current/pipeline_transformations/': plugins,
                '/api/projects/:team_id/pipeline_transformation_configs/': pluginConfigs,
                // TODO: Differentiate between transformation and destination mocks for nicer mocks
                '/api/organizations/@current/pipeline_destinations/': plugins,
                '/api/projects/:team_id/pipeline_destination_configs/': pluginConfigs,
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

export function PipelineAppConfiguration(): JSX.Element {
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

export function PipelineAppConfigurationEmpty(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipelineNode(PipelineStage.Destination, geoIpConfigId, PipelineNodeTab.Configuration))
    }, [])
    return <App />
}

export function PipelineAppConfiguration404(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipelineNode(PipelineStage.Destination, 4239084923809, PipelineNodeTab.Configuration))
    }, [])
    return <App />
}

export function PipelineAppMetrics(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipelineNode(PipelineStage.Destination, geoIpConfigId, PipelineNodeTab.Metrics))
        pipelineNodeMetricsLogic({ pluginConfigId: geoIpConfigId }).mount()
    }, [])
    return <App />
}

export function PipelineAppMetricsErrorModal(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipelineNode(PipelineStage.Destination, geoIpConfigId, PipelineNodeTab.Metrics))
        const logic = pipelineNodeMetricsLogic({ pluginConfigId: geoIpConfigId })
        logic.mount()
        logic.actions.openErrorDetailsModal('Error')
    }, [])
    return <App />
}

export function PipelineAppLogs(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/plugin_configs/:plugin_config_id/logs': require('./__mocks__/pluginLogs.json'),
        },
    })
    useEffect(() => {
        router.actions.push(urls.pipelineNode(PipelineStage.Destination, geoIpConfigId, PipelineNodeTab.Logs))
    }, [])
    return <App />
}

export function PipelineAppLogsBatchExport(): JSX.Element {
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

export function PipelineAppsManagementPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTab.AppsManagement))
        appsManagementLogic.mount()
    }, [])
    return <App />
}
