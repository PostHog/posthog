import { Meta, StoryObj } from '@storybook/react'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
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

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Pipeline',
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
                '/api/environments/:team_id/external_data_sources/wizard': empty,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        mockDate: '2023-02-18',
        featureFlags: [FEATURE_FLAGS.PIPELINE_UI],
    },
}
export default meta

const eventSequenceTimerPluginId = plugins.results.find((plugin) => plugin.name === 'Event Sequence Timer Plugin')!.id
const eventSequenceTimerPluginConfigId = pluginConfigs.results.find(
    (conf) => conf.plugin === eventSequenceTimerPluginId
)!.id
const geoIpConfigId = pluginConfigs.results.find(
    (conf) => conf.plugin === plugins.results.find((plugin) => plugin.name === 'GeoIP')!.id
)!.id

// A wrapper that enables the data pipelines feature flag
const AppWithDataPipelines = (): JSX.Element | null => {
    useAvailableFeatures([AvailableFeature.DATA_PIPELINES])
    return <App />
}

type Story = StoryObj<typeof meta>
export const PipelineLandingPage: Story = { parameters: { pageUrl: urls.pipeline() } }

export const PipelineOverviewPage: Story = { parameters: { pageUrl: urls.pipeline(PipelineTab.Overview) } }

export const PipelineTransformationsPage: Story = {
    parameters: { pageUrl: urls.pipeline(PipelineTab.Transformations) },
}
export const PipelineTransformationsPageEmpty: Story = {
    ...PipelineTransformationsPage,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/pipeline_transformation_configs/': empty,
            },
        }),
    ],
}

export const PipelineDestinationsPage: Story = { parameters: { pageUrl: urls.pipeline(PipelineTab.Destinations) } }
export const PipelineDestinationsPageWithPipelines: Story = {
    ...PipelineDestinationsPage,
    render: () => <AppWithDataPipelines />,
}

export const PipelineSiteAppsPage: Story = { parameters: { pageUrl: urls.pipeline(PipelineTab.SiteApps) } }

export const PipelineLegacySourcesPage: Story = {
    parameters: { pageUrl: urls.pipeline(PipelineTab.ImportApps) },
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/:organization_id/pipeline_import_apps/': plugins,
                '/api/projects/:team_id/pipeline_import_apps_configs/': pluginConfigs,
                '/api/projects/:team_id/pipeline_import_apps_configs/:id': pluginConfigRetrieveMock,
            },
        }),
    ],
}

export const PipelineLandingPageIffLegacySources: Story = {
    parameters: { pageUrl: urls.pipeline() },
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/:organization_id/pipeline_import_apps/': plugins,
                '/api/projects/:team_id/pipeline_import_apps_configs/': pluginConfigs,
                '/api/projects/:team_id/pipeline_import_apps_configs/:id': pluginConfigRetrieveMock,
            },
        }),
    ],
}

export const PipelineNodeNewTransformation: Story = {
    parameters: { pageUrl: urls.pipelineNodeNew(PipelineStage.Transformation) },
}

export const PipelineNodeNewDestination: Story = {
    parameters: { pageUrl: urls.pipelineNodeNew(PipelineStage.Destination) },
}
export const PipelineNodeNewDestinationWithDataPipelines: Story = {
    ...PipelineNodeNewDestination,
    render: () => <AppWithDataPipelines />,
}

export const PipelineNodeNewSequenceTimer: Story = {
    parameters: { pageUrl: urls.pipelineNodeNew(PipelineStage.Transformation, { id: eventSequenceTimerPluginId }) },
}

export const PipelineNodeNewBigQuery: Story = {
    parameters: { pageUrl: urls.pipelineNodeNew(PipelineStage.Destination, { id: 'BigQuery' }) },
}
export const PipelineNodeNewBigQueryWithDataPipelines: Story = {
    ...PipelineNodeNewBigQuery,
    render: () => <AppWithDataPipelines />,
}

export const PipelineNodeNewHogFunction: Story = {
    parameters: { pageUrl: urls.pipelineNodeNew(PipelineStage.Destination, { id: 'hog-template-slack' }) },
}

export const PipelineNodeEditConfiguration: Story = {
    parameters: {
        pageUrl: urls.pipelineNode(
            PipelineStage.Destination,
            eventSequenceTimerPluginConfigId,
            PipelineNodeTab.Configuration
        ),
    },
}

export const PipelineNodeEditConfigurationStatelessPlugin: Story = {
    parameters: {
        pageUrl: urls.pipelineNode(PipelineStage.Transformation, geoIpConfigId, PipelineNodeTab.Configuration),
    },
}

export const PipelineNodeConfiguration404: Story = {
    parameters: {
        pageUrl: urls.pipelineNode(PipelineStage.Transformation, 4239084923809, PipelineNodeTab.Configuration),
    },
}

export function PipelineNodeMetrics(): JSX.Element {
    useEffect(() => {
        pipelineNodeMetricsLogic({ id: geoIpConfigId }).mount()
    }, [])

    return <App />
}
PipelineNodeMetrics.parameters = {
    pageUrl: urls.pipelineNode(PipelineStage.Transformation, geoIpConfigId, PipelineNodeTab.Metrics),
}

export function PipelineNodeMetricsErrorModal(): JSX.Element {
    useEffect(() => {
        const logic = pipelineNodeMetricsLogic({ id: geoIpConfigId })
        logic.mount()
        logic.actions.openErrorDetailsModal('Error')
    }, [])

    return <App />
}
PipelineNodeMetricsErrorModal.parameters = {
    pageUrl: urls.pipelineNode(PipelineStage.Transformation, geoIpConfigId, PipelineNodeTab.Metrics),
}

export const PipelineNodeLogs: Story = {
    parameters: { pageUrl: urls.pipelineNode(PipelineStage.Transformation, geoIpConfigId, PipelineNodeTab.Logs) },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/plugin_configs/:plugin_config_id/logs': require('./__mocks__/pluginLogs.json'),
            },
        }),
    ],
}

export const PipelineNodeLogsBatchExport: Story = {
    parameters: {
        pageUrl: urls.pipelineNode(PipelineStage.Destination, batchExports.results[0].id, PipelineNodeTab.Logs),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/batch_exports/:export_id/logs': require('./__mocks__/batchExportLogs.json'),
            },
        }),
    ],
}

export function PipelineNodesManagementPage(): JSX.Element {
    useEffect(() => {
        appsManagementLogic.mount()
    }, [])

    return <App />
}
PipelineNodesManagementPage.parameters = { pageUrl: urls.pipeline(PipelineTab.AppsManagement) }
