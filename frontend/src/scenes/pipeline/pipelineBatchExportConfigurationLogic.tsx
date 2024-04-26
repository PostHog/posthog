import { afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { BatchExportConfiguration, BatchExportService, PipelineNodeTab, PipelineStage } from '~/types'

import { pipelineDestinationsLogic } from './destinationsLogic'
import type { pipelineBatchExportConfigurationLogicType } from './pipelineBatchExportConfigurationLogicType'

export interface PipelineBatchExportConfigurationLogicProps {
    service: BatchExportService['type'] | null
    id: string | null
}

// TODO:
function getConfigurationFromBatchExportConfig(config: BatchExportConfiguration): BatchExportConfiguration {
    return config
}

// TODO:
function getDefaultConfiguration(service: BatchExportService['type']): Record<string, any> {
    return {
        enabled: false,
        name: service,
    }
}

// Should likely be somewhat similar to pipelinePluginConfigurationLogic
export const pipelineBatchExportConfigurationLogic = kea<pipelineBatchExportConfigurationLogicType>([
    props({} as PipelineBatchExportConfigurationLogicProps),
    key(({ service, id }: PipelineBatchExportConfigurationLogicProps) => {
        if (id) {
            return `ID:${id}`
        }
        return `NEW:${service}`
    }),
    path((id) => ['scenes', 'pipeline', 'pipelineBatchExportConfigurationLogic', id]),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    loaders(({ props }) => ({
        batchExportConfig: [
            null as BatchExportConfiguration | null,
            {
                loadBatchExportConfig: async () => {
                    if (props.id) {
                        return await api.batchExports.get(props.id)
                    }
                    return null
                },
                updateBatchExportConfig: async (formdata) => {
                    if (props.id) {
                        const res = await api.batchExports.update(props.id, formdata)
                        return res
                    }
                    const res = await api.batchExports.create(formdata)
                    router.actions.replace(
                        urls.pipelineNode(PipelineStage.Destination, res.id, PipelineNodeTab.Configuration)
                    )
                    return res
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        configuration: [
            props.service ? getDefaultConfiguration(props.service) : ({} as Record<string, any>),
            {
                loadBatchExportConfigSuccess: (state, { batchExportConfig }) => {
                    if (!batchExportConfig) {
                        // if no props.id given loaded null, keep the default configuration
                        return state
                    }
                    return getConfigurationFromBatchExportConfig(batchExportConfig)
                },
                updateBatchExportConfigSuccess: ({ batchExportConfig }) => {
                    return getConfigurationFromBatchExportConfig(batchExportConfig)
                },
            },
        ],
    })),
    selectors({
        savedConfiguration: [
            (s, p) => [s.batchExportConfig, p.service],
            (batchExportConfig, service) => {
                if (!batchExportConfig || !service) {
                    return {}
                }
                if (batchExportConfig) {
                    return getConfigurationFromBatchExportConfig(batchExportConfig)
                }
                if (service) {
                    return getDefaultConfiguration(service)
                }
            },
        ],
        isNew: [(_, p) => [p.id], (id): boolean => !id],
    }),
    listeners(() => ({
        updateBatchExportConfigSuccess: ({ batchExportConfig }) => {
            if (!batchExportConfig) {
                return
            }
            pipelineDestinationsLogic.findMounted()?.actions.updateBatchExportConfig(batchExportConfig)
        },
    })),
    forms(({ asyncActions }) => ({
        configuration: {
            submit: async (formdata) => {
                await asyncActions.updateBatchExportConfig(formdata)
            },
        },
    })),
    afterMount(({ actions }) => {
        actions.loadBatchExportConfig()
    }),
])
