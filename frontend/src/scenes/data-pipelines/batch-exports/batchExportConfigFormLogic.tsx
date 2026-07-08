import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { addProductIntent } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DatabaseSchemaBatchExportTable, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import {
    BatchExportConfiguration,
    BatchExportConfigurationTest,
    BatchExportConfigurationTestStep,
    BatchExportService,
} from '~/types'

import type { batchExportConfigFormLogicType } from './batchExportConfigFormLogicType'
import { batchExportDataLogic } from './batchExportDataLogic'
import { DESTINATIONS } from './destinations'
import { genericPersonEventFields, isSelectedCompressionOptionValid } from './destinations/common'
import { humanizeBatchExportName } from './utils'

export interface BatchExportConfigFormLogicProps {
    service: BatchExportService['type'] | null
    id: string | null
}

// Fields that exist on the form but are not part of destination.config
const TOP_LEVEL_FORM_FIELDS = new Set([
    'name',
    'destination',
    'interval',
    'timezone',
    'offset_day',
    'offset_hour',
    'paused',
    'created_at',
    'start_at',
    'end_at',
    'model',
    'filters',
    'integration_id',
])

const ALLOWED_BASE_CONFIG_KEYS = new Set(['exclude_events', 'include_events'])

function buildDestinationPayload(formValues: Record<string, any>): {
    type: string
    config: Record<string, any>
    integration?: any
} {
    const destinationType = formValues.destination as BatchExportService['type']
    const definition = DESTINATIONS[destinationType]
    // Apply destination-specific transform first (e.g. Redshift's COPY copy_inputs assembly).
    // Destinations without a custom serialize get the raw form values passed through.
    const intermediate = definition?.serialize ? definition.serialize(formValues) : formValues
    // When a destination declares configKeys, drop any config key outside it (plus the base-export
    // keys). Mirrors the backend's allowed = destination_fields ∪ base_field_names check, so stale
    // fields don't survive a deserialize → serialize round-trip and get rejected on save.
    const allowed = definition?.configKeys ? new Set([...definition.configKeys, ...ALLOWED_BASE_CONFIG_KEYS]) : null
    // Strip top-level form fields that don't belong in destination.config
    const config: Record<string, any> = {}
    for (const [key, value] of Object.entries(intermediate)) {
        if (TOP_LEVEL_FORM_FIELDS.has(key)) {
            continue
        }
        if (allowed && !allowed.has(key)) {
            continue
        }
        config[key] = value
    }
    // A persisted compression value can be invalid for the selected file_format (e.g. an
    // externally-created JSONLines export still carrying a Parquet-only codec). Drop it on save so
    // editing an unrelated field doesn't resubmit a combination the backend rejects.
    if ('compression' in config && !isSelectedCompressionOptionValid(config.file_format, config.compression)) {
        config.compression = null
    }
    const result: { type: string; config: Record<string, any>; integration?: any } = {
        type: destinationType,
        config,
    }
    if (definition?.usesIntegration) {
        result.integration = formValues.integration_id
    }
    return result
}

function getConfigurationFromBatchExportConfig(batchExportConfig: BatchExportConfiguration): Record<string, any> {
    const destinationType = batchExportConfig.destination.type
    const definition = DESTINATIONS[destinationType]

    const flatConfig = definition?.deserialize
        ? definition.deserialize(batchExportConfig.destination.config)
        : { ...batchExportConfig.destination.config }

    const config: Record<string, any> = {
        name: batchExportConfig.name,
        destination: destinationType,
        paused: batchExportConfig.paused,
        interval: batchExportConfig.interval,
        timezone: batchExportConfig.timezone,
        offset_day: (batchExportConfig as any).offset_day ?? null,
        offset_hour: (batchExportConfig as any).offset_hour ?? null,
        model: batchExportConfig.model,
        filters: batchExportConfig.filters,
        ...flatConfig,
    }

    if (definition?.usesIntegration) {
        // Only the integration-backed destinations (Databricks, AzureBlob, BigQuery) carry this field.
        config.integration_id = (batchExportConfig.destination as { integration?: number }).integration
    }

    return config
}

export function getDefaultConfiguration(service: string): Record<string, any> {
    const definition = DESTINATIONS[service as BatchExportService['type']]
    return {
        name: humanizeBatchExportName(service as BatchExportService['type']),
        destination: service,
        model: 'events',
        paused: true,
        ...(definition ? definition.defaults() : {}),
    }
}

const BASE_EVENT_FIELDS = {
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
} as const

function getEventTable(service: BatchExportService['type']): DatabaseSchemaBatchExportTable {
    const definition = DESTINATIONS[service]
    const overrides = definition?.eventTableOverrides ?? {}
    const includeGeneric = overrides.includeGenericPersonFields !== false

    return {
        type: 'batch_export',
        id: 'Events',
        name: 'events',
        fields: {
            ...BASE_EVENT_FIELDS,
            ...(includeGeneric
                ? genericPersonEventFields({
                      teamIdHogql: overrides.teamIdHogql ?? 'team_id',
                      setName: overrides.setName ?? 'set',
                      setOnceName: overrides.setOnceName ?? 'set_once',
                  })
                : {}),
            ...definition?.eventTableExtraFields,
        },
    }
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
        entry_gclsrc: {
            name: 'entry_gclsrc',
            type: 'string',
            hogql_value: 'entry_gclsrc',
            schema_valid: true,
        },
        entry_dclid: {
            name: 'entry_dclid',
            type: 'string',
            hogql_value: 'entry_dclid',
            schema_valid: true,
        },
        entry_gbraid: {
            name: 'entry_gbraid',
            type: 'string',
            hogql_value: 'entry_gbraid',
            schema_valid: true,
        },
        entry_wbraid: {
            name: 'entry_wbraid',
            type: 'string',
            hogql_value: 'entry_wbraid',
            schema_valid: true,
        },
        entry_msclkid: {
            name: 'entry_msclkid',
            type: 'string',
            hogql_value: 'entry_msclkid',
            schema_valid: true,
        },
        entry_twclid: {
            name: 'entry_twclid',
            type: 'string',
            hogql_value: 'entry_twclid',
            schema_valid: true,
        },
        entry_li_fat_id: {
            name: 'entry_li_fat_id',
            type: 'string',
            hogql_value: 'entry_li_fat_id',
            schema_valid: true,
        },
        entry_mc_cid: {
            name: 'entry_mc_cid',
            type: 'string',
            hogql_value: 'entry_mc_cid',
            schema_valid: true,
        },
        entry_igshid: {
            name: 'entry_igshid',
            type: 'string',
            hogql_value: 'entry_igshid',
            schema_valid: true,
        },
        entry_ttclid: {
            name: 'entry_ttclid',
            type: 'string',
            hogql_value: 'entry_ttclid',
            schema_valid: true,
        },
        entry__kx: {
            name: 'entry__kx',
            type: 'string',
            hogql_value: 'entry__kx',
            schema_valid: true,
        },
        entry_irclid: {
            name: 'entry_irclid',
            type: 'string',
            hogql_value: 'entry_irclid',
            schema_valid: true,
        },
    },
}

// Form logic for creating and editing batch export configurations.
// Owns form state, validation, dirty-checking, test steps, and save/delete actions.
// Reads the underlying config data from batchExportDataLogic.
// Per-destination behaviour (defaults, required fields, payload assembly, validation, JSX) lives
// in the registry under ./destinations/. This file is destination-agnostic.
export const batchExportConfigFormLogic = kea<batchExportConfigFormLogicType>([
    props({ id: null, service: null } as BatchExportConfigFormLogicProps),
    key(({ service, id }: BatchExportConfigFormLogicProps) => {
        if (id) {
            return `ID:${id}`
        }
        return `NEW:${service}`
    }),
    path((key) => ['scenes', 'data-pipelines', 'batch-exports', 'batchExportConfigFormLogic', key]),
    connect((props: BatchExportConfigFormLogicProps) => ({
        values: [
            teamLogic,
            ['timezone as teamTimezone', 'weekStartDay as teamWeekStartDay'],
            batchExportDataLogic({ id: props.id }),
            ['batchExportConfig', 'batchExportConfigLoading'],
        ],
        actions: [
            batchExportDataLogic({ id: props.id }),
            ['loadBatchExportConfig', 'loadBatchExportConfigSuccess', 'setBatchExportConfig'],
        ],
    })),
    actions({
        setSavedConfiguration: (configuration: Record<string, any>) => ({ configuration }),
        setSelectedModel: (model: string) => ({ model }),
        setRunningStep: (step: number | null) => ({ step }),
        deleteBatchExport: () => true,
        updateBatchExportConfig: (formdata: Record<string, any>) => ({ formdata }),
        updateBatchExportConfigSuccess: (batchExportConfig: BatchExportConfiguration) => ({ batchExportConfig }),
    }),
    loaders(({ props, values, actions }) => ({
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

                    const formValues = values.configuration
                    const interval = formValues.interval
                    const data = {
                        paused: formValues.paused,
                        name: formValues.name,
                        interval,
                        timezone: interval === 'day' || interval === 'week' ? formValues.timezone : null,
                        offset_day: interval === 'week' ? formValues.offset_day : null,
                        offset_hour: interval === 'day' || interval === 'week' ? formValues.offset_hour : null,
                        model: formValues.model,
                        filters: formValues.filters,
                        destination: buildDestinationPayload(formValues),
                    } as any

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
        logicProps: [() => [(_, props) => props], (props) => props],
        service: [(s, p) => [s.batchExportConfig, p.service], (config, service) => config?.destination.type || service],
        isNew: [(_, p) => [p.id], (id): boolean => !id],
        loading: [
            (s) => [s.batchExportConfigLoading, s.batchExportConfigTestLoading],
            (batchExportConfigLoading, batchExportConfigTestLoading) =>
                batchExportConfigLoading || batchExportConfigTestLoading,
        ],
        isDatabaseDestination: [
            (s) => [s.service],
            (service): boolean =>
                !!service && ['Postgres', 'Redshift', 'Snowflake', 'Databricks', 'BigQuery'].includes(service),
        ],
        requiredFields: [
            (s) => [s.service, s.isNew, s.configuration],
            (service, isNew, config): string[] => {
                const generalRequiredFields = ['interval', 'name', 'model']
                if (!service) {
                    return generalRequiredFields
                }
                const definition = DESTINATIONS[service as BatchExportService['type']]
                if (!definition) {
                    return generalRequiredFields
                }
                return [...generalRequiredFields, ...definition.requiredFields({ isNew, formValues: config })]
            },
        ],
    })),
    listeners(({ props, values, actions }) => ({
        updateBatchExportConfig: async ({ formdata }) => {
            const interval = formdata.interval
            const data: Omit<BatchExportConfiguration, 'id' | 'team_id' | 'created_at' | 'start_at' | 'end_at'> = {
                paused: formdata.paused,
                name: formdata.name,
                interval,
                timezone: interval === 'day' || interval === 'week' ? formdata.timezone : null,
                offset_day: interval === 'week' ? formdata.offset_day : null,
                offset_hour: interval === 'day' || interval === 'week' ? formdata.offset_hour : null,
                model: formdata.model,
                filters: formdata.filters,
                destination: buildDestinationPayload(formdata) as any,
            } as any

            if (props.id) {
                const res = await api.batchExports.update(props.id, data)
                lemonToast.success('Batch export configuration updated successfully')
                void addProductIntent({
                    product_type: ProductKey.PIPELINE_BATCH_EXPORTS,
                    intent_context: ProductIntentContext.BATCH_EXPORT_UPDATED,
                })
                actions.setBatchExportConfig(res)
                actions.updateBatchExportConfigSuccess(res)
                return
            }
            const res = await api.batchExports.create(data)
            actions.resetConfiguration(getConfigurationFromBatchExportConfig(res))

            void addProductIntent({
                product_type: ProductKey.PIPELINE_BATCH_EXPORTS,
                intent_context: ProductIntentContext.BATCH_EXPORT_CREATED,
            })

            router.actions.replace(urls.batchExport(res.id))
            lemonToast.success('Batch export created successfully')
            actions.updateBatchExportConfigSuccess(res)
        },
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

            // Set timezone to team's timezone if interval is day/week but timezone is not set
            // Check values.configuration since the reducer has already updated it
            if (
                (values.configuration.interval === 'day' || values.configuration.interval === 'week') &&
                !values.configuration.timezone
            ) {
                const teamTz = values.teamTimezone || 'UTC'
                actions.setConfigurationValue('timezone', teamTz)
            }
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
                    (step.result.status === 'Passed' || step.result.status === 'Skipped') &&
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
        setConfigurationValue: ({ name, value }) => {
            const fieldName = Array.isArray(name) ? name[0] : name

            if (fieldName === 'file_format') {
                // Pick a compression that's valid for the newly-selected format, in priority order:
                //   1. keep the current codec if it still fits (e.g. gzip works for both formats);
                //   2. otherwise, when returning to the format the export was saved with, restore the
                //      persisted codec — so a Parquet→JSONLines→Parquet round-trip recovers the saved
                //      compression rather than stranding the export on a default;
                //   3. otherwise fall back to the format's default (zstd for Parquet, none for JSONLines).
                const current = values.configuration.compression
                const saved = values.savedConfiguration
                let next: string | null
                if (current !== null && isSelectedCompressionOptionValid(value, current)) {
                    next = current
                } else if (value === saved.file_format && isSelectedCompressionOptionValid(value, saved.compression)) {
                    next = saved.compression
                } else {
                    next = value === 'Parquet' ? 'zstd' : null
                }
                if (next !== current) {
                    actions.setConfigurationValue('compression', next)
                }
            }

            if (fieldName === 'interval') {
                // if changing to day or week, set the timezone to the team's timezone if not already set
                if (value === 'day' || value === 'week') {
                    // if we didn't have a timezone set before, set it to the team's timezone
                    if (values.savedConfiguration.interval !== 'day' && values.savedConfiguration.interval !== 'week') {
                        const teamTz = values.teamTimezone || 'UTC'
                        actions.setConfigurationValue('timezone', teamTz)
                    }
                    // if changing to week, set the day of the week to the team's week start day
                    if (value === 'week') {
                        const weekStartDay = values.teamWeekStartDay || 0
                        actions.setConfigurationValue('offset_day', weekStartDay)
                        actions.setConfigurationValue('offset_hour', 0)
                    }
                } else {
                    // Clear timezone and offset when interval is not day or week
                    actions.setConfigurationValue('timezone', null)
                    actions.setConfigurationValue('offset_day', null)
                    actions.setConfigurationValue('offset_hour', null)
                }
            }
        },
        deleteBatchExport: async () => {
            // TODO: support undo'ing a delete
            const batchExportId = values.batchExportConfig?.id
            if (!batchExportId) {
                return
            }
            try {
                await api.batchExports.delete(batchExportId)
                lemonToast.success('Batch export deleted successfully')
                router.actions.replace(urls.destinations())
            } catch (error: any) {
                // Show error toast with the error message from the API
                const errorMessage = error.detail || error.message || 'Failed to delete'
                lemonToast.error(errorMessage)
            }
        },
    })),
    forms(({ asyncActions, values }) => ({
        configuration: {
            errors: (formdata) => {
                const requiredFieldErrors = Object.fromEntries(
                    values.requiredFields.map((field) => [
                        field,
                        formdata[field] ? undefined : 'This field is required',
                    ])
                )

                const destination = formdata.destination as BatchExportService['type'] | undefined
                const definition = destination ? DESTINATIONS[destination] : undefined
                const fieldValidations = definition?.validate?.(formdata) ?? {}

                // Only apply a field validation when it produced a message — a valid (undefined)
                // result must not clobber a "required" error from the same empty field.
                const errors: Record<string, string | undefined> = { ...requiredFieldErrors }
                for (const [field, message] of Object.entries(fieldValidations)) {
                    if (message) {
                        errors[field] = message
                    }
                }
                return errors
            },
            submit: async (formdata) => {
                // Check if schedule fields have changed and show confirmation modal
                const scheduleFieldsChanged =
                    formdata.interval !== values.savedConfiguration.interval ||
                    formdata.timezone !== values.savedConfiguration.timezone ||
                    formdata.offset_day !== values.savedConfiguration.offset_day ||
                    formdata.offset_hour !== values.savedConfiguration.offset_hour

                if (!values.isNew && scheduleFieldsChanged) {
                    let userConfirmed = false
                    await new Promise<void>((resolve) => {
                        LemonDialog.open({
                            title: 'Confirm schedule change',
                            description: (
                                <>
                                    <p>
                                        Changing the schedule (interval, timezone, or start time) of a batch export
                                        could result in a gap of data.
                                    </p>
                                    <p>
                                        Make sure to run a backfill if necessary to ensure all data is exported
                                        correctly.
                                    </p>
                                </>
                            ),
                            primaryButton: {
                                children: 'Save changes',
                                onClick: () => {
                                    userConfirmed = true
                                    resolve()
                                },
                            },
                            secondaryButton: {
                                children: 'Cancel',
                                onClick: () => {
                                    userConfirmed = false
                                    resolve()
                                },
                            },
                        })
                    })

                    // Only proceed with submission if user confirmed
                    if (!userConfirmed) {
                        return
                    }
                }

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
        actions.loadBatchExportConfigTest()
    }),
])
