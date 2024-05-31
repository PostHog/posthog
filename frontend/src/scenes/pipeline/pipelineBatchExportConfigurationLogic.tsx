import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { BatchExportConfigurationForm } from 'scenes/batch_exports/batchExportEditLogic'
import { urls } from 'scenes/urls'

import { BatchExportConfiguration, BatchExportService, PipelineNodeTab, PipelineStage } from '~/types'

import { sanitizeFilters } from './configUtils'
import { pipelineDestinationsLogic } from './destinationsLogic'
import { pipelineAccessLogic } from './pipelineAccessLogic'
import type { pipelineBatchExportConfigurationLogicType } from './pipelineBatchExportConfigurationLogicType'

export interface PipelineBatchExportConfigurationLogicProps {
    service: BatchExportService['type'] | null
    id: string | null
}

function getConfigurationFromBatchExportConfig(batchExportConfig: BatchExportConfiguration): Record<string, any> {
    return {
        name: batchExportConfig.name,
        destination: batchExportConfig.destination.type,
        paused: batchExportConfig.paused,
        interval: batchExportConfig.interval,
        filters: batchExportConfig.filters,
        ...batchExportConfig.destination.config,
    }
}

function getDefaultConfiguration(service: BatchExportService['type']): Record<string, any> {
    return {
        name: service,
        destination: service,
        paused: true,
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
        values: [pipelineAccessLogic, ['canEnableNewDestinations'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setSavedConfiguration: (configuration: Record<string, any>) => ({ configuration }),
    }),
    loaders(({ props, values }) => ({
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
                    if (
                        (!values.batchExportConfig || (values.batchExportConfig.paused && formdata.paused !== true)) &&
                        !values.canEnableNewDestinations
                    ) {
                        lemonToast.error('Data pipelines add-on is required for enabling new destinations.')
                        return null
                    }
                    const { name, destination, interval, paused, filters, created_at, start_at, end_at, ...config } =
                        formdata
                    const destinationObj = {
                        type: destination,
                        config: config,
                    }
                    const data: Omit<
                        BatchExportConfiguration,
                        'id' | 'team_id' | 'created_at' | 'start_at' | 'end_at'
                    > = {
                        paused,
                        name,
                        interval,
                        filters: sanitizeFilters(filters),
                        destination: destinationObj,
                    }
                    if (props.id) {
                        const res = await api.batchExports.update(props.id, data)
                        return res
                    }
                    const res = await api.batchExports.create(data)
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
            props.service ? getDefaultConfiguration(props.service) : ({} as BatchExportConfigurationForm),
            {
                loadBatchExportConfigSuccess: (state, { batchExportConfig }) => {
                    if (!batchExportConfig) {
                        return state
                    }
                    return getConfigurationFromBatchExportConfig(batchExportConfig)
                },
                updateBatchExportConfigSuccess: (state, { batchExportConfig }) => {
                    if (!batchExportConfig) {
                        return state
                    }
                    return getConfigurationFromBatchExportConfig(batchExportConfig)
                },
            },
        ],
    })),
    selectors(() => ({
        service: [(s, p) => [s.batchExportConfig, p.service], (config, service) => config?.destination.type || service],
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
                return {} as Record<string, any>
            },
        ],
        isNew: [(_, p) => [p.id], (id): boolean => !id],
        requiredFields: [
            (s) => [s.service],
            (service): string[] => {
                const generalRequiredFields = ['interval', 'name']
                if (service === 'Postgres') {
                    return [
                        ...generalRequiredFields,
                        'user',
                        'password',
                        'host',
                        'port',
                        'database',
                        'schema',
                        'table_name',
                    ]
                } else if (service === 'Redshift') {
                    return [
                        ...generalRequiredFields,
                        'user',
                        'password',
                        'host',
                        'port',
                        'database',
                        'schema',
                        'table_name',
                    ]
                } else if (service === 'S3') {
                    return [
                        ...generalRequiredFields,
                        'bucket_name',
                        'region',
                        'prefix',
                        'aws_access_key_id',
                        'aws_secret_access_key',
                        'file_format',
                    ]
                } else if (service === 'BigQuery') {
                    return [...generalRequiredFields, 'json_config_file', 'dataset_id', 'table_id']
                } else if (service === 'HTTP') {
                    return [...generalRequiredFields, 'url', 'token']
                } else if (service === 'Snowflake') {
                    return [
                        ...generalRequiredFields,
                        'account',
                        'database',
                        'warehouse',
                        'user',
                        'password',
                        'schema',
                        'table_name',
                    ]
                }
                return generalRequiredFields
            },
        ],

        filteringEnabled: [
            (s) => [s.featureFlags, s.batchExportConfig],
            (featureFlags, batchExportConfig): boolean => {
                return !!batchExportConfig?.filters || !!featureFlags[FEATURE_FLAGS.BATCH_EXPORT_FILTERING]
            },
        ],
    })),
    listeners(({ values, actions }) => ({
        updateBatchExportConfigSuccess: ({ batchExportConfig }) => {
            if (!batchExportConfig) {
                return
            }
            pipelineDestinationsLogic.findMounted()?.actions.updateBatchExportConfig(batchExportConfig)
        },
        setConfigurationValue: async ({ name, value }) => {
            if (name[0] === 'json_config_file' && value) {
                try {
                    const loadedFile: string = await new Promise((resolve, reject) => {
                        const filereader = new FileReader()
                        filereader.onload = (e) => resolve(e.target?.result as string)
                        filereader.onerror = (e) => reject(e)
                        filereader.readAsText(value[0])
                    })
                    const jsonConfig = JSON.parse(loadedFile)
                    actions.setConfigurationValues({
                        ...values.configuration,
                        project_id: jsonConfig.project_id,
                        private_key: jsonConfig.private_key,
                        private_key_id: jsonConfig.private_key_id,
                        client_email: jsonConfig.client_email,
                        token_uri: jsonConfig.token_uri,
                    })
                } catch (e) {
                    actions.setConfigurationManualErrors({
                        json_config_file: 'The config file is not valid',
                    })
                }
            }
        },
    })),
    forms(({ asyncActions, values }) => ({
        configuration: {
            errors: (formdata) => {
                return Object.fromEntries(
                    values.requiredFields.map((field) => [
                        field,
                        formdata[field] ? undefined : 'This field is required',
                    ])
                )
            },
            submit: async (formdata) => {
                await asyncActions.updateBatchExportConfig(formdata)
            },
        },
    })),
    beforeUnload(({ actions, values }) => ({
        enabled: () => values.configurationChanged,
        message: 'Leave action?\nChanges you made will be discarded.',
        onConfirm: () => {
            actions.resetConfiguration()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadBatchExportConfig()
    }),
])
