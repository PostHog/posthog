import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { PipelineAppTabs, PipelineTabs } from '~/types'

import { appMetricsLogic } from './appMetricsLogic'
import { appsManagementLogic } from './appsManagementLogic'
import { pipelineLogic } from './pipelineLogic'

export default {
    title: 'Scenes-App/Pipeline',
    decorators: [
        // mocks used by all stories in this file
        mswDecorator({
            get: {
                'api/organizations/@current/pipeline_transformations/': {},
                'api/organizations/@current/plugins/': {},
                'api/projects/:team_id/pipeline_transformations_configs/': {},
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
        router.actions.push(urls.pipeline(PipelineTabs.Filters))
        pipelineLogic.mount()
    }, [])
    return <App />
}

export function PipelineTransformationsPageEmpty(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTabs.Transformations))
        pipelineLogic.mount()
    }, [])
    return <App />
}

export function PipelineTransformationsPage(): JSX.Element {
    useStorybookMocks({
        get: {
            'api/organizations/@current/pipeline_transformations/': require('./__mocks__/plugins.json'),
            'api/projects/:team_id/pipeline_transformations_configs/': require('./__mocks__/transformationPluginConfigs.json'),
        },
    })
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTabs.Transformations))
        pipelineLogic.mount()
    }, [])
    return <App />
}
export function PipelineDestinationsPage(): JSX.Element {
    useStorybookMocks({
        get: {
            'api/organizations/@current/pipeline_destinations/': require('./__mocks__/plugins.json'),
            'api/projects/:team_id/pipeline_destinations_configs/': require('./__mocks__/transformationPluginConfigs.json'),
        },
    })
    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTabs.Destinations))
        pipelineLogic.mount()
    }, [])
    return <App />
}

export function PipelineAppConfiguration(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.pipelineApp(1, PipelineAppTabs.Configuration))
    }, [])
    return <App />
}

export function PipelineAppMetrics(): JSX.Element {
    useStorybookMocks({
        get: {
            'api/projects/:team_id/app_metrics/4?date_from=-7d': require('./__mocks__/pluginMetrics.json'),
            'api/projects/:team_id/app_metrics/4/error_details?error_type=Error': require('./__mocks__/pluginErrorDetails.json'),
        },
    })
    useEffect(() => {
        router.actions.push(urls.pipelineApp(4, PipelineAppTabs.Metrics))
        appMetricsLogic({ pluginConfigId: 4 }).mount()
    }, [])
    return <App />
}

export function PipelineAppMetricsErrorModal(): JSX.Element {
    useStorybookMocks({
        get: {
            'api/projects/:team_id/app_metrics/4?date_from=-7d': require('./__mocks__/pluginMetrics.json'),
            'api/projects/:team_id/app_metrics/4/error_details?error_type=Error': require('./__mocks__/pluginErrorDetails.json'),
        },
    })
    useEffect(() => {
        router.actions.push(urls.pipelineApp(4, PipelineAppTabs.Metrics))
        const logic = appMetricsLogic({ pluginConfigId: 4 })
        logic.mount()
        logic.actions.openErrorDetailsModal('Error')
    }, [])
    return <App />
}

export function PipelineAppLogs(): JSX.Element {
    useStorybookMocks({
        get: {
            'api/projects/:team_id/plugin_configs/1/logs': require('./__mocks__/pluginLogs.json'),
        },
    })
    useEffect(() => {
        router.actions.push(urls.pipelineApp(1, PipelineAppTabs.Logs))
    }, [])
    return <App />
}

export function PipelineAppsManagementPage(): JSX.Element {
    useStorybookMocks({
        get: {
            'api/organizations/@current/plugins/': require('./__mocks__/plugins.json'),
        },
    })

    useEffect(() => {
        router.actions.push(urls.pipeline(PipelineTabs.AppsManagement))
        appsManagementLogic.mount()
    }, [])
    return <App />
}
