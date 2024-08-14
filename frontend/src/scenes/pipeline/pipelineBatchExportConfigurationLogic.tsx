import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import { DatabaseSchemaBatchExportTable } from '~/queries/schema'
import { BatchExportConfiguration, BatchExportService, PipelineNodeTab, PipelineStage } from '~/types'

import { BatchExportConfigurationForm } from './batch-exports/types'
import { humanizeBatchExportName } from './batch-exports/utils'
import { pipelineDestinationsLogic } from './destinations/destinationsLogic'
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
        model: batchExportConfig.model,
        ...batchExportConfig.destination.config,
    }
}

function getDefaultConfiguration(service: BatchExportService['type']): Record<string, any> {
    return {
        name: humanizeBatchExportName(service),
        destination: service,
        model: 'events',
        paused: true,
    }
}

function getEventTable(service: BatchExportService['type']): DatabaseSchemaBatchExportTable {
    const eventsTable: DatabaseSchemaBatchExportTable = {
        type: 'batch_export',
        id: 'Events',
        name: 'events',
        fields: {
            uuid: {
                name: 'uuid',
                hogql_value: 'toString(uuid)',
                type: 'string',
                schema_valid: true,
            },
            timestamp: {
                name: 'timestamp',
                hogql_value: 'timestamp',
                type: 'datetime',
                schema_valid: true,
            },
            event: {
                name: 'event',
                hogql_value: 'event',
                type: 'string',
                schema_valid: true,
            },
            distinct_id: {
                name: 'distinct_id',
                hogql_value: 'toString(distinct_id)',
                type: 'string',
                schema_valid: true,
            },
            properties: {
                name: 'properties',
                hogql_value: 'properties',
                type: 'json',
                schema_valid: true,
            },
            ...(service == 'S3' && {
                person_id: {
                    name: 'person_id',
                    hogql_value: 'toString(person_id)',
                    type: 'string',
                    schema_valid: true,
                },
                person_properties: {
                    name: 'person_properties',
                    hogql_value: "nullIf(person_properties, '')",
                    type: 'string',
                    schema_valid: true,
                },
                created_at: {
                    name: 'created_at',
                    hogql_value: 'created_at',
                    type: 'datetime',
                    schema_valid: true,
                },
            }),
            ...(service != 'S3' && {
                team_id: {
                    name: 'team_id',
                    hogql_value: service == 'Postgres' || service == 'Redshift' ? 'toInt32(team_id)' : 'team_id',
                    type: 'integer',
                    schema_valid: true,
                },
                set: {
                    name: service == 'Snowflake' ? 'people_set' : 'set',
                    hogql_value: "nullIf(JSONExtractString(properties, '$set'), '')",
                    type: 'string',
                    schema_valid: true,
                },
                set_once: {
                    name: service == 'Snowflake' ? 'people_set_once' : 'set_once',
                    hogql_value: "nullIf(JSONExtractString(properties, '$set_once'), '')",
                    type: 'string',
                    schema_valid: true,
                },
                site_url: {
                    name: 'site_url',
                    hogql_value: "''",
                    type: 'string',
                    schema_valid: true,
                },
                ip: {
                    name: 'ip',
                    hogql_value: "nullIf(JSONExtractString(properties, '$ip'), '')",
                    type: 'string',
                    schema_valid: true,
                },
                elements_chain: {
                    name: 'elements',
                    hogql_value: 'toJSONString(elements_chain)',
                    type: 'string',
                    schema_valid: true,
                },
            }),
            ...(service == 'BigQuery' && {
                bq_ingested_timestamp: {
                    name: 'bq_ingested_timestamp',
                    hogql_value: 'NOW64()',
                    type: 'datetime',
                    schema_valid: true,
                },
            }),
        },
    }

    return eventsTable
}

const personsTable: DatabaseSchemaBatchExportTable = {
    type: 'batch_export',
    id: 'Persons',
    name: 'persons',
    fields: {
        team_id: {
            name: 'team_id',
            hogql_value: 'team_id',
            type: 'integer',
            schema_valid: true,
        },
        distinct_id: {
            name: 'distinct_id',
            hogql_value: 'distinct_id',
            type: 'string',
            schema_valid: true,
        },
        person_id: {
            name: 'person_id',
            hogql_value: 'person_id',
            type: 'string',
            schema_valid: true,
        },
        properties: {
            name: 'properties',
            hogql_value: 'properties',
            type: 'json',
            schema_valid: true,
        },
        person_version: {
            name: 'person_version',
            hogql_value: 'person_version',
            type: 'integer',
            schema_valid: true,
        },
        person_distinct_id_version: {
            name: 'person_distinct_id_version',
            hogql_value: 'person_distinct_id_version',
            type: 'integer',
            schema_valid: true,
        },
    },
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
        values: [pipelineAccessLogic, ['canEnableNewDestinations']],
    })),
    actions({
        setSavedConfiguration: (configuration: Record<string, any>) => ({ configuration }),
        setSelectedModel: (model: string) => ({ model }),
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
                    const { name, destination, interval, paused, created_at, start_at, end_at, model, ...config } =
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
                        model,
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
        tables: [
            props.service ? [getEventTable(props.service), personsTable] : ([] as DatabaseSchemaBatchExportTable[]),
            {
                loadBatchExportConfigSuccess: (state, { batchExportConfig }) => {
                    if (!batchExportConfig) {
                        return state
                    }

                    return [getEventTable(batchExportConfig.destination.type), personsTable]
                },
                updateBatchExportConfigSuccess: (state, { batchExportConfig }) => {
                    if (!batchExportConfig) {
                        return state
                    }

                    return [getEventTable(batchExportConfig.destination.type), personsTable]
                },
            },
        ],
        selectedModel: [
            'events',
            {
                setSelectedModel: (_, { model }) => model,
                loadBatchExportConfigSuccess: (state, { batchExportConfig }) => {
                    if (!batchExportConfig) {
                        return state
                    }

                    return batchExportConfig.model
                },
                updateBatchExportConfigSuccess: (state, { batchExportConfig }) => {
                    if (!batchExportConfig) {
                        return state
                    }
                    return batchExportConfig.model
                },
            },
        ],
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
            (s) => [s.service, s.isNew],
            (service, isNew): string[] => {
                const generalRequiredFields = ['interval', 'name', 'model']
                if (service === 'Postgres') {
                    return [
                        ...generalRequiredFields,
                        ...(isNew ? ['user'] : []),
                        ...(isNew ? ['password'] : []),
                        'host',
                        'port',
                        'database',
                        'schema',
                        'table_name',
                    ]
                } else if (service === 'Redshift') {
                    return [
                        ...generalRequiredFields,
                        ...(isNew ? ['user'] : []),
                        ...(isNew ? ['password'] : []),
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
                        ...(isNew ? ['aws_access_key_id'] : []),
                        ...(isNew ? ['aws_secret_access_key'] : []),
                        ...(isNew ? ['file_format'] : []),
                    ]
                } else if (service === 'BigQuery') {
                    return [...generalRequiredFields, ...(isNew ? ['json_config_file'] : []), 'dataset_id', 'table_id']
                } else if (service === 'HTTP') {
                    return [...generalRequiredFields, 'url', 'token']
                } else if (service === 'Snowflake') {
                    return [
                        ...generalRequiredFields,
                        'account',
                        'database',
                        'warehouse',
                        ...(isNew ? ['user'] : []),
                        ...(isNew ? ['password'] : []),
                        'schema',
                        'table_name',
                    ]
                }
                return generalRequiredFields
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
