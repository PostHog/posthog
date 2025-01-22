import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import { DatabaseSchemaBatchExportTable } from '~/queries/schema'
import { BatchExportConfiguration, BatchExportService, PipelineNodeTab, PipelineStage } from '~/types'

import { humanizeBatchExportName } from './batch-exports/utils'
import { DESTINATION_TYPES } from './destinations/constants'
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
    },
}

const sessionsTable: DatabaseSchemaBatchExportTable = {
    type: 'batch_export',
    id: 'Sesssions',
    name: 'sessions',
    fields: {
        team_id: {
            name: 'team_id',
            type: 'string',
            hogql_value: 'team_id',
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
        min_timestamp: {
            name: 'min_timestamp',
            type: 'datetime',
            hogql_value: 'min_timestamp',
            schema_valid: true,
        },
        max_timestamp: {
            name: 'max_timestamp',
            type: 'datetime',
            hogql_value: 'max_timestamp',
            schema_valid: true,
        },
        inserted_at: {
            name: 'inserted_at',
            type: 'datetime',
            hogql_value: 'inserted_at',
            schema_valid: true,
        },
        urls: {
            name: 'urls',
            type: 'string',
            hogql_value: 'urls',
            schema_valid: true,
        },
        entry_url: {
            name: 'entry_url',
            type: 'string',
            hogql_value: 'entry_url',
            schema_valid: true,
        },
        end_url: {
            name: 'end_url',
            type: 'string',
            hogql_value: 'end_url',
            schema_valid: true,
        },
        last_external_click_url: {
            name: 'last_external_click_url',
            type: 'string',
            hogql_value: 'last_external_click_url',
            schema_valid: true,
        },
        initial_browser: {
            name: 'initial_browser',
            type: 'string',
            hogql_value: 'initial_browser',
            schema_valid: true,
        },
        initial_browser_version: {
            name: 'initial_browser_version',
            type: 'string',
            hogql_value: 'initial_browser_version',
            schema_valid: true,
        },
        initial_os: {
            name: 'initial_os',
            type: 'string',
            hogql_value: 'initial_os',
            schema_valid: true,
        },
        initial_os_version: {
            name: 'initial_os_version',
            type: 'string',
            hogql_value: 'initial_os_version',
            schema_valid: true,
        },
        initial_device_type: {
            name: 'initial_device_type',
            type: 'string',
            hogql_value: 'initial_device_type',
            schema_valid: true,
        },
        initial_viewport_width: {
            name: 'initial_viewport_width',
            type: 'string',
            hogql_value: 'initial_viewport_width',
            schema_valid: true,
        },
        initial_viewport_height: {
            name: 'initial_viewport_height',
            type: 'string',
            hogql_value: 'initial_viewport_height',
            schema_valid: true,
        },
        initial_geoip_country_code: {
            name: 'initial_geoip_country_code',
            type: 'string',
            hogql_value: 'initial_geoip_country_code',
            schema_valid: true,
        },
        initial_geoip_subdivision_1_code: {
            name: 'initial_geoip_subdivision_1_code',
            type: 'string',
            hogql_value: 'initial_geoip_subdivision_1_code',
            schema_valid: true,
        },
        initial_geoip_subdivision_1_name: {
            name: 'initial_geoip_subdivision_1_name',
            type: 'string',
            hogql_value: 'initial_geoip_subdivision_1_name',
            schema_valid: true,
        },
        initial_geoip_subdivision_city_name: {
            name: 'initial_geoip_subdivision_city_name',
            type: 'string',
            hogql_value: 'initial_geoip_subdivision_city_name',
            schema_valid: true,
        },
        initial_geoip_time_zone: {
            name: 'initial_geoip_time_zone',
            type: 'string',
            hogql_value: 'initial_geoip_time_zone',
            schema_valid: true,
        },
        initial_referring_domain: {
            name: 'initial_referring_domain',
            type: 'string',
            hogql_value: 'initial_referring_domain',
            schema_valid: true,
        },
        initial_utm_source: {
            name: 'initial_utm_source',
            type: 'string',
            hogql_value: 'initial_utm_source',
            schema_valid: true,
        },
        initial_utm_campaign: {
            name: 'initial_utm_campaign',
            type: 'string',
            hogql_value: 'initial_utm_campaign',
            schema_valid: true,
        },
        initial_utm_medium: {
            name: 'initial_utm_medium',
            type: 'string',
            hogql_value: 'initial_utm_medium',
            schema_valid: true,
        },
        initial_utm_term: {
            name: 'initial_utm_term',
            type: 'string',
            hogql_value: 'initial_utm_term',
            schema_valid: true,
        },
        initial_utm_content: {
            name: 'initial_utm_content',
            type: 'string',
            hogql_value: 'initial_utm_content',
            schema_valid: true,
        },
        initial_gclid: {
            name: 'initial_gclid',
            type: 'string',
            hogql_value: 'initial_gclid',
            schema_valid: true,
        },
        initial_gad_source: {
            name: 'initial_gad_source',
            type: 'string',
            hogql_value: 'initial_gad_source',
            schema_valid: true,
        },
        initial_gclsrc: {
            name: 'initial_gclsrc',
            type: 'string',
            hogql_value: 'initial_gclsrc',
            schema_valid: true,
        },
        initial_dclid: {
            name: 'initial_dclid',
            type: 'string',
            hogql_value: 'initial_dclid',
            schema_valid: true,
        },
        initial_gbraid: {
            name: 'initial_gbraid',
            type: 'string',
            hogql_value: 'initial_gbraid',
            schema_valid: true,
        },
        initial_wbraid: {
            name: 'initial_wbraid',
            type: 'string',
            hogql_value: 'initial_wbraid',
            schema_valid: true,
        },
        initial_fbclid: {
            name: 'initial_fbclid',
            type: 'string',
            hogql_value: 'initial_fbclid',
            schema_valid: true,
        },
        initial_msclkid: {
            name: 'initial_msclkid',
            type: 'string',
            hogql_value: 'initial_msclkid',
            schema_valid: true,
        },
        initial_twclid: {
            name: 'initial_twclid',
            type: 'string',
            hogql_value: 'initial_twclid',
            schema_valid: true,
        },
        initial_li_fat_id: {
            name: 'initial_li_fat_id',
            type: 'string',
            hogql_value: 'initial_li_fat_id',
            schema_valid: true,
        },
        initial_mc_cid: {
            name: 'initial_mc_cid',
            type: 'string',
            hogql_value: 'initial_mc_cid',
            schema_valid: true,
        },
        initial_igshid: {
            name: 'initial_igshid',
            type: 'string',
            hogql_value: 'initial_igshid',
            schema_valid: true,
        },
        initial_ttclid: {
            name: 'initial_ttclid',
            type: 'string',
            hogql_value: 'initial_ttclid',
            schema_valid: true,
        },
        pageview_count: {
            name: 'pageview_count',
            type: 'string',
            hogql_value: 'pageview_count',
            schema_valid: true,
        },
        pageview_uniq: {
            name: 'pageview_uniq',
            type: 'string',
            hogql_value: 'pageview_uniq',
            schema_valid: true,
        },
        autocapture_count: {
            name: 'autocapture_count',
            type: 'string',
            hogql_value: 'autocapture_count',
            schema_valid: true,
        },
        autocapture_uniq: {
            name: 'autocapture_uniq',
            type: 'string',
            hogql_value: 'autocapture_uniq',
            schema_valid: true,
        },
        screen_count: {
            name: 'screen_count',
            type: 'string',
            hogql_value: 'screen_count',
            schema_valid: true,
        },
        screen_uniq: {
            name: 'screen_uniq',
            type: 'string',
            hogql_value: 'screen_uniq',
            schema_valid: true,
        },
        maybe_has_session_replay: {
            name: 'maybe_has_session_replay',
            type: 'string',
            hogql_value: 'maybe_has_session_replay',
            schema_valid: true,
        },
        page_screen_autocapture_uniq_up_to: {
            name: 'page_screen_autocapture_uniq_up_to',
            type: 'string',
            hogql_value: 'page_screen_autocapture_uniq_up_to',
            schema_valid: true,
        },
        vitals_lcp: {
            name: 'vitals_lcp',
            type: 'string',
            hogql_value: 'vitals_lcp',
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
    loaders(({ props, actions }) => ({
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

                    router.actions.replace(
                        urls.pipelineNode(PipelineStage.Destination, res.id, PipelineNodeTab.Configuration)
                    )
                    lemonToast.success('Batch export created successfully')
                    return res
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

            pipelineDestinationsLogic
                .findMounted({ types: DESTINATION_TYPES })
                ?.actions.updateBatchExportConfig(batchExportConfig)
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
            values.batchExportConfig
                ? actions.resetConfiguration(getConfigurationFromBatchExportConfig(values.batchExportConfig))
                : values.service
                ? actions.resetConfiguration(getDefaultConfiguration(values.service))
                : actions.resetConfiguration()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadBatchExportConfig()
    }),
])
