import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import { DatabaseSchemaBatchExportTable } from '~/queries/schema/schema-general'
import {
    BatchExportConfiguration,
    BatchExportConfigurationTest,
    BatchExportConfigurationTestStep,
    BatchExportService,
} from '~/types'

import { pipelineAccessLogic } from '../../pipeline/pipelineAccessLogic'
import type { batchExportConfigurationLogicType } from './batchExportConfigurationLogicType'
import { humanizeBatchExportName } from './utils'

export interface BatchExportConfigurationLogicProps {
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
        filters: batchExportConfig.filters,
        ...batchExportConfig.destination.config,
    }
}

export function getDefaultConfiguration(service: string): Record<string, any> {
    return {
        name: humanizeBatchExportName(service as BatchExportService['type']),
        destination: service,
        model: 'events',
        paused: true,
        ...(service === 'Snowflake' && {
            authentication_type: 'password',
        }),
        ...(service === 'S3' && {
            file_format: 'Parquet',
            compression: 'zstd',
        }),
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
        created_at: {
            name: 'created_at',
            hogql_value: 'created_at',
            type: 'datetime',
            schema_valid: true,
        },
        is_deleted: {
            name: 'is_deleted',
            hogql_value: 'is_deleted',
            type: 'boolean',
            schema_valid: true,
        },
    },
}

const sessionsTable: DatabaseSchemaBatchExportTable = {
    type: 'batch_export',
    id: 'Sessions',
    name: 'sessions',
    fields: {
        team_id: {
            name: 'team_id',
            hogql_value: 'team_id',
            type: 'integer',
            schema_valid: true,
        },
        session_id: {
            name: 'session_id',
            type: 'string',
            hogql_value: 'session_id',
            schema_valid: true,
        },
        session_id_v7: {
            name: 'session_id_v7',
            type: 'string',
            hogql_value: 'session_id_v7',
            schema_valid: true,
        },
        distinct_id: {
            name: 'distinct_id',
            type: 'string',
            hogql_value: 'distinct_id',
            schema_valid: true,
        },
        start_timestamp: {
            name: 'start_timestamp',
            type: 'datetime',
            hogql_value: 'start_timestamp',
            schema_valid: true,
        },
        end_timestamp: {
            name: 'end_timestamp',
            type: 'datetime',
            hogql_value: 'end_timestamp',
            schema_valid: true,
        },
        urls: {
            name: 'urls',
            type: 'array',
            hogql_value: 'urls',
            schema_valid: true,
        },
        num_uniq_urls: {
            name: 'num_uniq_urls',
            type: 'integer',
            hogql_value: 'num_uniq_urls',
            schema_valid: true,
        },
        entry_current_url: {
            name: 'entry_current_url',
            type: 'string',
            hogql_value: 'entry_current_url',
            schema_valid: true,
        },
        entry_pathname: {
            name: 'entry_pathname',
            type: 'string',
            hogql_value: 'entry_pathname',
            schema_valid: true,
        },
        entry_hostname: {
            name: 'entry_hostname',
            type: 'string',
            hogql_value: 'entry_hostname',
            schema_valid: true,
        },
        end_current_url: {
            name: 'end_current_url',
            type: 'string',
            hogql_value: 'end_current_url',
            schema_valid: true,
        },
        end_pathname: {
            name: 'end_pathname',
            type: 'string',
            hogql_value: 'end_pathname',
            schema_valid: true,
        },
        end_hostname: {
            name: 'end_hostname',
            type: 'string',
            hogql_value: 'end_hostname',
            schema_valid: true,
        },
        entry_utm_source: {
            name: 'entry_utm_source',
            type: 'string',
            hogql_value: 'entry_utm_source',
            schema_valid: true,
        },
        entry_utm_campaign: {
            name: 'entry_utm_campaign',
            type: 'string',
            hogql_value: 'entry_utm_campaign',
            schema_valid: true,
        },
        entry_utm_medium: {
            name: 'entry_utm_medium',
            type: 'string',
            hogql_value: 'entry_utm_medium',
            schema_valid: true,
        },
        entry_utm_term: {
            name: 'entry_utm_term',
            type: 'string',
            hogql_value: 'entry_utm_term',
            schema_valid: true,
        },
        entry_utm_content: {
            name: 'entry_utm_content',
            type: 'string',
            hogql_value: 'entry_utm_content',
            schema_valid: true,
        },
        entry_referring_domain: {
            name: 'entry_referring_domain',
            type: 'string',
            hogql_value: 'entry_referring_domain',
            schema_valid: true,
        },
        entry_gclid: {
            name: 'entry_gclid',
            type: 'string',
            hogql_value: 'entry_gclid',
            schema_valid: true,
        },
        entry_fbclid: {
            name: 'entry_fbclid',
            type: 'string',
            hogql_value: 'entry_fbclid',
            schema_valid: true,
        },
        entry_gad_source: {
            name: 'entry_gad_source',
            type: 'string',
            hogql_value: 'entry_gad_source',
            schema_valid: true,
        },
        pageview_count: {
            name: 'pageview_count',
            type: 'integer',
            hogql_value: 'pageview_count',
            schema_valid: true,
        },
        autocapture_count: {
            name: 'autocapture_count',
            type: 'integer',
            hogql_value: 'autocapture_count',
            schema_valid: true,
        },
        screen_count: {
            name: 'screen_count',
            type: 'integer',
            hogql_value: 'screen_count',
            schema_valid: true,
        },
        channel_type: {
            name: 'channel_type',
            type: 'string',
            hogql_value: 'channel_type',
            schema_valid: true,
        },
        session_duration: {
            name: 'session_duration',
            type: 'integer',
            hogql_value: 'session_duration',
            schema_valid: true,
        },
        duration: {
            name: 'duration',
            type: 'integer',
            hogql_value: 'duration',
            schema_valid: true,
        },
        is_bounce: {
            name: 'is_bounce',
            type: 'boolean',
            hogql_value: 'is_bounce',
            schema_valid: true,
        },
        last_external_click_url: {
            name: 'last_external_click_url',
            type: 'string',
            hogql_value: 'last_external_click_url',
            schema_valid: true,
        },
        page_screen_autocapture_count_up_to: {
            name: 'page_screen_autocapture_count_up_to',
            type: 'string',
            hogql_value: 'page_screen_autocapture_count_up_to',
            schema_valid: true,
        },
        exit_current_url: {
            name: 'exit_current_url',
            type: 'string',
            hogql_value: 'exit_current_url',
            schema_valid: true,
        },
        exit_pathname: {
            name: 'exit_pathname',
            type: 'string',
            hogql_value: 'exit_pathname',
            schema_valid: true,
        },
        vital_lcp: {
            name: 'vital_lcp',
            type: 'float',
            hogql_value: 'vital_lcp',
            schema_valid: true,
        },
    },
}

export const batchExportConfigurationLogic = kea<batchExportConfigurationLogicType>([
    props({} as BatchExportConfigurationLogicProps),
    key(({ service, id }: BatchExportConfigurationLogicProps) => {
        if (id) {
            return `ID:${id}`
        }
        return `NEW:${service}`
    }),
    path((id) => ['scenes', 'data-pipelines', 'batch-exports', 'batchExportConfigurationLogic', id]),
    connect(() => ({
        values: [pipelineAccessLogic, ['canEnableNewDestinations']],
    })),
    actions({
        setSavedConfiguration: (configuration: Record<string, any>) => ({ configuration }),
        setSelectedModel: (model: string) => ({ model }),
        setRunningStep: (step: number | null) => ({ step }),
    }),
    loaders(({ props, actions, values }) => ({
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
                    const {
                        name,
                        destination,
                        interval,
                        paused,
                        created_at,
                        start_at,
                        end_at,
                        model,
                        filters,
                        ...config
                    } = formdata
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
                        filters,
                        destination: destinationObj,
                    }
                    if (props.id) {
                        const res = await api.batchExports.update(props.id, data)
                        lemonToast.success('Batch export configuration updated successfully')
                        return res
                    }
                    const res = await api.batchExports.create(data)
                    actions.resetConfiguration(getConfigurationFromBatchExportConfig(res))

                    router.actions.replace(urls.batchExport(res.id))
                    lemonToast.success('Batch export created successfully')
                    return res
                },
            },
        ],
        batchExportConfigTest: [
            null as BatchExportConfigurationTest | null,
            {
                loadBatchExportConfigTest: async () => {
                    if (props.service) {
                        try {
                            return await api.batchExports.test(props.service)
                        } catch {
                            return null
                        }
                    }
                    return null
                },
                updateBatchExportConfigTest: async (service) => {
                    if (service) {
                        try {
                            return await api.batchExports.test(service)
                        } catch {
                            return null
                        }
                    }
                    return null
                },
            },
        ],
        batchExportConfigTestStep: [
            null as BatchExportConfigurationTestStep | null,
            {
                runBatchExportConfigTestStep: async (step) => {
                    if (!values.batchExportConfigTest) {
                        return null
                    }

                    actions.setRunningStep(step)
                    if (step === 0) {
                        // TODO: Allow re-running steps that failed
                        values.batchExportConfigTest.steps.forEach((step) => {
                            step.result = null
                        })
                    }
                    const {
                        name,
                        destination,
                        interval,
                        paused,
                        created_at,
                        start_at,
                        end_at,
                        model,
                        filters,
                        ...config
                    } = values.configuration
                    const destinationObj = {
                        type: destination,
                        config: config,
                    }
                    const data = {
                        paused,
                        name,
                        interval,
                        model,
                        filters,
                        destination: destinationObj,
                    }

                    if (props.id) {
                        return await api.batchExports.runTestStep(props.id, step, data)
                    }
                    return await api.batchExports.runTestStepNew(step, data)
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        tables: [
            props.service
                ? [getEventTable(props.service), personsTable, sessionsTable]
                : ([] as DatabaseSchemaBatchExportTable[]),
            {
                loadBatchExportConfigSuccess: (state, { batchExportConfig }) => {
                    if (!batchExportConfig) {
                        return state
                    }

                    return [getEventTable(batchExportConfig.destination.type), personsTable, sessionsTable]
                },
                updateBatchExportConfigSuccess: (state, { batchExportConfig }) => {
                    if (!batchExportConfig) {
                        return state
                    }

                    return [getEventTable(batchExportConfig.destination.type), personsTable, sessionsTable]
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
            props.service ? getDefaultConfiguration(props.service) : ({} as Record<string, any>),
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
        savedConfiguration: [
            {} as Record<string, any>,
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
        runningStep: [
            null as number | null,
            {
                setRunningStep: (_, { step }) => step,
            },
        ],
    })),
    selectors(() => ({
        service: [(s, p) => [s.batchExportConfig, p.service], (config, service) => config?.destination.type || service],
        isNew: [(_, p) => [p.id], (id): boolean => !id],
        requiredFields: [
            (s) => [s.service, s.isNew, s.configuration],
            (service, isNew, config): string[] => {
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
                        ...(isNew && config.authentication_type == 'password' ? ['password'] : []),
                        ...(isNew && config.authentication_type == 'keypair' ? ['private_key'] : []),
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

            // Reset so that form doesn't think there are unsaved changes.
            actions.resetConfiguration(getConfigurationFromBatchExportConfig(batchExportConfig))
        },
        loadBatchExportConfigSuccess: ({ batchExportConfig }) => {
            if (!batchExportConfig) {
                return
            }

            actions.updateBatchExportConfigTest(batchExportConfig.destination.type)
        },
        runBatchExportConfigTestStepSuccess: ({ batchExportConfigTestStep }) => {
            if (!values.batchExportConfigTest) {
                return
            }

            const step = batchExportConfigTestStep || values.batchExportConfigTestStep
            if (!step) {
                return
            }

            const index = values.batchExportConfigTest.steps.findIndex((item) => item.name === step.name)

            if (index > -1) {
                values.batchExportConfigTest.steps[index] = step

                if (
                    step.result &&
                    step.result.status === 'Passed' &&
                    index < values.batchExportConfigTest.steps.length - 1
                ) {
                    actions.runBatchExportConfigTestStep(index + 1)
                } else {
                    actions.setRunningStep(null)
                }
            }
        },
        runBatchExportConfigTestStepFailure: () => {
            if (!values.batchExportConfigTest || !values.runningStep) {
                return
            }

            values.batchExportConfigTest.steps[values.runningStep].result = {
                status: 'Failed',
                message: `The batch export configuration could not be correctly serialized. Required fields may be missing or have invalid values`,
            }
            actions.setRunningStep(null)
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
                } catch {
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
            values.batchExportConfig
                ? actions.resetConfiguration(getConfigurationFromBatchExportConfig(values.batchExportConfig))
                : values.service
                ? actions.resetConfiguration(getDefaultConfiguration(values.service))
                : actions.resetConfiguration()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadBatchExportConfig()
        actions.loadBatchExportConfigTest()
    }),
])
