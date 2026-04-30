import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import {
    VALID_NON_NATIVE_MARKETING_SOURCES,
    VALID_SELF_MANAGED_MARKETING_SOURCES,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import {
    ExternalDataSourceType,
    ProductIntentContext,
    ProductKey,
    SourceConfig,
    SourceFieldConfig,
    SourceFieldSwitchGroupConfig,
    SuggestedTable,
    VALID_NATIVE_MARKETING_SOURCES,
    externalDataSources,
} from '~/queries/schema/schema-general'
import {
    Breadcrumb,
    ExternalDataSourceCreatePayload,
    ExternalDataSourceSyncSchema,
    IncrementalField,
    ManualLinkSourceType,
    manualLinkSources,
} from '~/types'

import {
    getDefaultExpandedDirectQuerySchemaKeys,
    groupDirectQueryTablesBySchema,
    splitDirectQueryTableName,
} from '../../shared/components/forms/directQuerySchemaUtils'
import type { WebhookCreateResult } from '../../shared/components/forms/WebhookSetupForm'
import { sourceManagementLogic } from '../../shared/logics/sourceManagementLogic'
import { selfManagedSourceLogic } from './selfManagedSourceLogic'
import type { sourceWizardLogicType } from './sourceWizardLogicType'
import { restoreSourceFormState, saveSourceFormState } from './wizardFormStorage'

export const SSH_FIELD: SourceFieldSwitchGroupConfig = {
    name: 'ssh_tunnel',
    label: 'Use SSH tunnel?',
    type: 'switch-group',
    default: false,
    fields: [
        {
            name: 'host',
            label: 'Tunnel host',
            type: 'text',
            required: true,
            placeholder: 'localhost',
            secret: false,
        },
        {
            name: 'port',
            label: 'Tunnel port',
            type: 'number',
            required: true,
            placeholder: '22',
            secret: false,
        },
        {
            type: 'select',
            name: 'auth',
            label: 'Authentication type',
            required: true,
            defaultValue: 'password',
            options: [
                {
                    label: 'Password',
                    value: 'password',
                    fields: [
                        {
                            name: 'username',
                            label: 'Tunnel username',
                            type: 'text',
                            required: true,
                            placeholder: 'User1',
                            secret: false,
                        },
                        {
                            name: 'password',
                            label: 'Tunnel password',
                            type: 'password',
                            required: true,
                            placeholder: '',
                            secret: true,
                        },
                    ],
                },
                {
                    label: 'Key pair',
                    value: 'keypair',
                    fields: [
                        {
                            name: 'username',
                            label: 'Tunnel username',
                            type: 'text',
                            required: false,
                            placeholder: 'User1',
                            secret: false,
                        },
                        {
                            name: 'private_key',
                            label: 'Tunnel private key',
                            type: 'textarea',
                            required: true,
                            placeholder: '',
                            secret: true,
                        },
                        {
                            name: 'passphrase',
                            label: 'Tunnel passphrase',
                            type: 'password',
                            required: false,
                            placeholder: '',
                            secret: true,
                        },
                    ],
                },
            ],
        },
        {
            name: 'require_tls',
            label: 'Require TLS through tunnel?',
            type: 'switch-group',
            default: true,
            caption: 'Disable if your database does not support TLS.',
            fields: [],
        },
    ],
}

export const buildKeaFormDefaultFromSourceDetails = (
    sourceDetails: Record<string, SourceConfig>
): Record<string, any> => {
    if (!sourceDetails) {
        return {}
    }

    const fieldDefaults = (field: SourceFieldConfig, obj: Record<string, any>): void => {
        if (field.type === 'switch-group') {
            obj[field.name] = {}
            obj[field.name]['enabled'] = field.default
            field.fields.forEach((f) => fieldDefaults(f, obj[field.name]))
            return
        }

        if (field.type === 'select') {
            const hasOptionFields = !!field.options.filter((n) => (n.fields?.length ?? 0) > 0).length

            if (hasOptionFields) {
                obj[field.name] = {}
                obj[field.name]['selection'] = field.defaultValue
                field.options.flatMap((n) => n.fields ?? []).forEach((f) => fieldDefaults(f, obj[field.name]))
            } else {
                obj[field.name] = field.defaultValue
            }
            return
        }

        // All other types
        obj[field.name] = ''
    }

    const sourceDetailsKeys = Object.keys(sourceDetails)
    return sourceDetailsKeys.reduce(
        (defaults, cur) => {
            const fields = sourceDetails[cur].fields
            fields.forEach((f) => {
                if (f.type === 'ssh-tunnel') {
                    fieldDefaults(SSH_FIELD, defaults['payload'])
                } else {
                    fieldDefaults(f, defaults['payload'])
                }
            })

            return defaults
        },
        { prefix: '', description: '', payload: {} } as Record<string, any>
    )
}

// Merge priority for the source connection form when a connector is (re)selected:
//   1. connector-schema defaults (lowest)
//   2. URL/UI access_method (e.g. `?access_method=direct`)
//   3. OAuth-restored values (highest — saved access_method wins over a stale URL one because
//      the OAuth callback URL doesn't carry it forward)
export function mergeRestoredSourceFormValues(
    defaults: Record<string, unknown>,
    savedValues: Record<string, unknown> | null | undefined,
    currentAccessMethod: unknown
): Record<string, unknown> {
    return {
        ...defaults,
        ...(currentAccessMethod !== undefined ? { access_method: currentAccessMethod } : {}),
        ...savedValues,
    }
}

const manualLinkSourceMap: Record<ManualLinkSourceType, string> = {
    aws: 'S3',
    'google-cloud': 'Google Cloud Storage',
    'cloudflare-r2': 'Cloudflare R2',
    azure: 'Azure',
}

const isTimestampType = (field: IncrementalField): boolean => {
    const type = field.type || field.field_type
    return type === 'timestamp' || type === 'datetime' || type === 'date'
}

const resolveIncrementalField = (fields: IncrementalField[]): IncrementalField | undefined => {
    // check for timestamp field matching "updated_at" or "updatedAt" case insensitive
    const updatedAt = fields.find((field) => {
        const regex = /^updated/i
        return regex.test(field.label) && isTimestampType(field)
    })
    if (updatedAt) {
        return updatedAt
    }
    // fallback to timestamp field matching "created_at" or "createdAt" case insensitive
    const createdAt = fields.find((field) => {
        const regex = /^created/i
        return regex.test(field.label) && isTimestampType(field)
    })
    if (createdAt) {
        return createdAt
    }
    // fallback to any timestamp or datetime field
    const timestamp = fields.find((field) => isTimestampType(field))
    if (timestamp) {
        return timestamp
    }
    // fallback to numeric fields matching "id" or "uuid" case insensitive
    const id = fields.find((field) => {
        const idRegex = /^id/i
        const uuidRegex = /^uuid/i
        return (idRegex.test(field.label) || uuidRegex.test(field.label)) && field.type === 'integer'
    })
    if (id) {
        return id
    }
    // leave unset and require user configuration
    return undefined
}

function syncExpandedDirectQuerySchemaKeys(
    actions: sourceWizardLogicType['actions'],
    values: sourceWizardLogicType['values']
): void {
    if (!values.isDirectQueryMode) {
        return
    }

    const fingerprint = values.groupedDirectQuerySchemaKeys.join('|')
    if (values.groupedDirectQuerySchemaKeysFingerprint === fingerprint) {
        return
    }

    actions.syncExpandedDirectQuerySchemaKeys(values.groupedDirectQuerySchemaKeys, fingerprint)
}

export interface SourceWizardLogicProps {
    onComplete?: () => void
    availableSources: Record<string, SourceConfig>
    /** When set, only these tables will be pre-selected and they cannot be deselected */
    requiredTables?: string[]
}

export const sourceWizardLogic = kea<sourceWizardLogicType>([
    path(['products', 'dataWarehouse', 'sourceWizardLogic']),
    props({} as SourceWizardLogicProps),
    actions({
        selectConnector: (connector: SourceConfig | null, accessMethod?: 'warehouse' | 'direct') => ({
            connector,
            accessMethod,
        }),
        setInitialConnector: (connector: SourceConfig | null) => ({ connector }),
        toggleManualLinkFormVisible: (visible: boolean) => ({ visible }),
        handleRedirect: (source: ExternalDataSourceType, searchParams?: any) => ({
            source,
            searchParams,
        }),
        setReturnConfig: (returnUrl: string, returnLabel: string) => ({ returnUrl, returnLabel }),
        clearReturnConfig: true,
        onClear: true,
        onBack: true,
        onNext: true,
        onSubmit: true,
        resetSourceForm: (accessMethod?: 'warehouse' | 'direct') => ({ accessMethod }),
        setDatabaseSchemas: (schemas: ExternalDataSourceSyncSchema[]) => ({
            schemas,
        }),
        toggleSchemaShouldSync: (schema: ExternalDataSourceSyncSchema, shouldSync: boolean) => ({ schema, shouldSync }),
        updateSchemaSyncType: (
            schema: ExternalDataSourceSyncSchema,
            syncType: ExternalDataSourceSyncSchema['sync_type'],
            incrementalField: string | null,
            incrementalFieldType: string | null,
            primaryKeyColumns: string[] | null,
            cdcTableMode?: 'consolidated' | 'cdc_only' | 'both'
        ) => ({
            schema,
            syncType,
            incrementalField,
            incrementalFieldType,
            primaryKeyColumns,
            cdcTableMode,
        }),
        clearSource: true,
        updateSource: (source: Partial<ExternalDataSourceCreatePayload>) => ({
            source,
        }),
        createSource: true,
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setSourceId: (id: string) => ({ sourceId: id }),
        closeWizard: true,
        cancelWizard: true,
        setStep: (step: number) => ({ step }),
        getDatabaseSchemas: true,
        setManualLinkingProvider: (provider: ManualLinkSourceType) => ({
            provider,
        }),
        openSyncMethodModal: (schema: ExternalDataSourceSyncSchema) => ({ schema }),
        cancelSyncMethodModal: true,
        toggleAllTables: (selectAll: boolean) => ({ selectAll }),
        toggleDirectQuerySchemaGroup: (schemaName: string, shouldSync: boolean) => ({ schemaName, shouldSync }),
        setExpandedDirectQuerySchemaKeys: (expandedSchemaKeys: string[]) => ({ expandedSchemaKeys }),
        syncExpandedDirectQuerySchemaKeys: (groupedSchemaKeys: string[], fingerprint: string) => ({
            groupedSchemaKeys,
            fingerprint,
        }),
        saveFormStateBeforeRedirect: true,
        createWebhook: true,
        setWebhookResult: (result: WebhookCreateResult | null) => ({
            result,
        }),
        submitWebhookFields: true,
        openCdcSelfManagedSetupDialog: true,
        closeCdcSelfManagedSetupDialog: true,
        clearCdcPrereqsCheckResult: true,
        clearCdcSelfManagedVerifyResult: true,
        touchAllSourceConnectionDetailsFields: true,
    }),
    connect(() => ({
        values: [
            selfManagedSourceLogic,
            ['tableLoading'],
            sourceManagementLogic,
            ['dataWarehouseSources'],
            preflightLogic,
            ['preflight'],
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeamId'],
        ],
        actions: [
            selfManagedSourceLogic,
            ['resetTable', 'createTableSuccess'],
            sourceManagementLogic,
            ['loadSources'],
            teamLogic,
            ['addProductIntent'],
            globalSetupLogic,
            ['markTaskAsCompleted'],
        ],
    })),
    reducers({
        manualLinkingProvider: [
            null as ManualLinkSourceType | null,
            {
                setManualLinkingProvider: (_, { provider }) => provider,
            },
        ],
        cdcSelfManagedSetupDialogOpen: [
            false,
            {
                openCdcSelfManagedSetupDialog: () => true,
                closeCdcSelfManagedSetupDialog: () => false,
                onClear: () => false,
            },
        ],
        selectedConnector: [
            null as SourceConfig | null,
            {
                selectConnector: (_, { connector }) => connector,
                setInitialConnector: (_, { connector }) => connector,
            },
        ],
        isManualLinkFormVisible: [
            false,
            {
                toggleManualLinkFormVisible: (_, { visible }) => visible,
            },
        ],
        currentStep: [
            1,
            {
                onNext: (state) => state + 1,
                onBack: (state) => state - 1,
                onClear: () => 1,
                setStep: (_, { step }) => step,
                setInitialConnector: () => 2,
            },
        ],
        databaseSchema: [
            [] as ExternalDataSourceSyncSchema[],
            {
                setDatabaseSchemas: (_, { schemas }) => schemas,
                toggleAllTables: (state, { selectAll }) => {
                    return state.map((schema) => ({
                        ...schema,
                        should_sync: selectAll,
                    }))
                },
                toggleSchemaShouldSync: (state, { schema, shouldSync }) => {
                    return state.map((s) => ({
                        ...s,
                        should_sync: s.table === schema.table ? shouldSync : s.should_sync,
                    }))
                },
                updateSchemaSyncType: (
                    state,
                    { schema, syncType, incrementalField, incrementalFieldType, primaryKeyColumns, cdcTableMode }
                ) => {
                    return state.map((s) => ({
                        ...s,
                        sync_type: s.table === schema.table ? syncType : s.sync_type,
                        incremental_field: s.table === schema.table ? incrementalField : s.incremental_field,
                        incremental_field_type:
                            s.table === schema.table ? incrementalFieldType : s.incremental_field_type,
                        primary_key_columns: s.table === schema.table ? primaryKeyColumns : s.primary_key_columns,
                        ...(s.table === schema.table && syncType === 'cdc' && cdcTableMode
                            ? { cdc_table_mode: cdcTableMode }
                            : {}),
                    }))
                },
            },
        ],
        expandedDirectQuerySchemaKeys: [
            [] as string[],
            {
                setExpandedDirectQuerySchemaKeys: (_, { expandedSchemaKeys }) => expandedSchemaKeys,
                syncExpandedDirectQuerySchemaKeys: (state, { groupedSchemaKeys }) => {
                    const nextKeys = state.filter((key) => groupedSchemaKeys.includes(key))
                    return nextKeys.length > 0 ? nextKeys : groupedSchemaKeys
                },
                onClear: () => [],
                clearSource: () => [],
            },
        ],
        groupedDirectQuerySchemaKeysFingerprint: [
            '',
            {
                syncExpandedDirectQuerySchemaKeys: (_, { fingerprint }) => fingerprint,
                onClear: () => '',
                clearSource: () => '',
            },
        ],
        source: [
            {
                payload: {},
                prefix: '',
                description: '',
                access_method: 'warehouse',
            } as {
                prefix: string
                description: string
                access_method: 'warehouse' | 'direct'
                payload: Record<string, any>
            },
            {
                updateSource: (state, { source }) => {
                    return {
                        prefix: source.prefix ?? state.prefix,
                        description: source.description ?? state.description,
                        access_method: source.access_method ?? state.access_method,
                        payload: {
                            ...state.payload,
                            ...source.payload,
                        },
                    }
                },
                clearSource: () => ({
                    payload: {},
                    prefix: '',
                    description: '',
                    access_method: 'warehouse',
                }),
            },
        ],
        isLoading: [
            false as boolean,
            {
                onNext: () => false,
                setIsLoading: (_, { isLoading }) => isLoading,
            },
        ],
        sourceId: [
            null as string | null,
            {
                setSourceId: (_, { sourceId }) => sourceId,
            },
        ],
        returnConfig: [
            null as { returnUrl: string; returnLabel: string } | null,
            {
                setReturnConfig: (_, { returnUrl, returnLabel }) => ({ returnUrl, returnLabel }),
                clearReturnConfig: () => null,
            },
        ],
        syncMethodModalOpen: [
            false as boolean,
            {
                openSyncMethodModal: () => true,
                cancelSyncMethodModal: () => false,
            },
        ],
        currentSyncMethodModalSchema: [
            null as ExternalDataSourceSyncSchema | null,
            {
                openSyncMethodModal: (_, { schema }) => schema,
                cancelSyncMethodModal: () => null,
                updateSchemaSyncType: (
                    _,
                    { schema, syncType, incrementalField, incrementalFieldType, primaryKeyColumns, cdcTableMode }
                ) => ({
                    ...schema,
                    sync_type: syncType,
                    incremental_field: incrementalField,
                    incremental_field_type: incrementalFieldType,
                    primary_key_columns: primaryKeyColumns,
                    ...(syncType === 'cdc' && cdcTableMode ? { cdc_table_mode: cdcTableMode } : {}),
                }),
            },
        ],
        webhookResult: [
            null as WebhookCreateResult | null,
            {
                setWebhookResult: (_, { result }) => result,
                onClear: () => null,
            },
        ],
        webhookCreating: [
            false,
            {
                createWebhook: () => true,
                setWebhookResult: () => false,
            },
        ],
    }),
    loaders(({ values }) => ({
        cdcPrereqsCheckResult: [
            null as { valid: boolean; errors: string[] } | null,
            {
                clearCdcPrereqsCheckResult: () => null,
                checkCdcPrereqs: async () => {
                    if (!values.currentTeamId) {
                        lemonToast.error('No project selected — reload the page and try again.')
                        return null
                    }
                    const payload = ((values.sourceConnectionDetails as any)?.payload || {}) as Record<string, any>
                    const mode = (payload.cdc_management_mode || 'posthog') as 'posthog' | 'self_managed'
                    try {
                        return await api.externalDataSources.check_cdc_prerequisites(
                            {
                                source_type: 'Postgres' as ExternalDataSourceType,
                                ...payload,
                                cdc_management_mode: mode,
                                tables: [],
                                cdc_slot_name: null,
                                cdc_publication_name: null,
                            },
                            values.currentTeamId
                        )
                    } catch (e: any) {
                        lemonToast.error(e?.detail || e?.message || 'Failed to check prerequisites')
                        return null
                    }
                },
            },
        ],
        cdcSelfManagedVerifyResult: [
            null as { valid: boolean; errors: string[] } | null,
            {
                clearCdcSelfManagedVerifyResult: () => null,
                verifyCdcSelfManagedSetup: async () => {
                    if (!values.currentTeamId) {
                        lemonToast.error('No project selected — reload the page and try again.')
                        return null
                    }
                    const sourcePayload = ((values.source as any)?.payload || {}) as Record<string, any>
                    const connectionPayload = ((values.sourceConnectionDetails as any)?.payload || {}) as Record<
                        string,
                        any
                    >
                    const pubName = (sourcePayload.cdc_publication_name as string) || 'posthog_pub'
                    const cdcTableNames = (values.databaseSchema || [])
                        .filter((s: any) => s.should_sync && s.sync_type === 'cdc')
                        .map((s: any) => s.table as string)
                    try {
                        return await api.externalDataSources.check_cdc_prerequisites(
                            {
                                source_type: 'Postgres' as ExternalDataSourceType,
                                ...connectionPayload,
                                cdc_management_mode: 'self_managed',
                                // PostHog creates the slot itself — only verify the publication.
                                cdc_slot_name: null,
                                cdc_publication_name: pubName,
                                tables: cdcTableNames,
                            },
                            values.currentTeamId
                        )
                    } catch (e: any) {
                        lemonToast.error(e?.detail || e?.message || 'Could not verify CDC setup')
                        return null
                    }
                },
            },
        ],
    })),
    selectors({
        availableSources: [() => [(_, p) => p.availableSources], (availableSources) => availableSources],
        requiredTables: [() => [(_, p) => p.requiredTables], (requiredTables) => requiredTables ?? null],
        // Form defaults derived from the selected connector's field schema. Returning a fresh
        // object on every connector change is cheap and keeps the form layer side-effect-free —
        // the `resetSourceForm` listener writes these into form state.
        defaultSourceConnectionDetails: [
            (s) => [s.selectedConnector],
            (selectedConnector: SourceConfig | null): Record<string, unknown> => {
                if (!selectedConnector) {
                    return { prefix: '', description: '', payload: {} }
                }
                return buildKeaFormDefaultFromSourceDetails({
                    [selectedConnector.name]: selectedConnector,
                })
            },
        ],
        suggestedTablesMap: [
            (s) => [s.selectedConnector],
            (selectedConnector: SourceConfig | null): Record<string, string | null> => {
                if (!selectedConnector?.suggestedTables) {
                    return {}
                }

                return selectedConnector.suggestedTables.reduce(
                    (acc: Record<string, string | null>, suggested: SuggestedTable) => {
                        acc[suggested.table] = suggested.tooltip ?? null
                        return acc
                    },
                    {} as Record<string, string | null>
                )
            },
        ],
        breadcrumbs: [
            (s) => [s.selectedConnector, s.manualLinkingProvider, s.manualConnectors],
            (selectedConnector, manualLinkingProvider, manualConnectors): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Sources,
                        name: 'Sources',
                        path: urls.sources(),
                        iconType: 'data_pipeline',
                    },
                    {
                        key: Scene.DataWarehouseSource,
                        name:
                            selectedConnector?.label ??
                            (manualLinkingProvider
                                ? manualConnectors.find((c) => c.type === manualLinkingProvider)?.name
                                : 'New'),
                        iconType: 'data_pipeline',
                    },
                ]
            },
        ],

        hasWebhookSchemas: [
            (s) => [s.databaseSchema],
            (databaseSchema: ExternalDataSourceSyncSchema[]): boolean =>
                databaseSchema.some((s) => s.supports_webhooks && s.sync_type === 'webhook' && s.should_sync),
        ],
        webhookStepComplete: [
            (s) => [s.webhookResult, s.selectedConnector],
            (webhookResult: WebhookCreateResult | null, selectedConnector: SourceConfig | null): boolean => {
                if (webhookResult?.success && (webhookResult.pending_inputs?.length ?? 0) === 0) {
                    return true
                }
                if (!webhookResult) {
                    return false
                }

                const webhookFields = selectedConnector?.webhookFields ?? []
                const requiredFields = webhookFields.filter((f) => 'required' in f && f.required)
                return requiredFields.length === 0
            },
        ],
        isManualLinkingSelected: [(s) => [s.selectedConnector], (selectedConnector): boolean => !selectedConnector],
        isDirectQueryMode: [
            (s) => [s.source, s.selectedConnector],
            (source, selectedConnector): boolean =>
                source.access_method === 'direct' && selectedConnector?.name === 'Postgres',
        ],
        canGoBack: [
            (s) => [s.currentStep],
            (currentStep): boolean => {
                return currentStep !== 4 && currentStep !== 5
            },
        ],
        canGoNext: [
            (s) => [
                s.currentStep,
                s.isManualLinkingSelected,
                s.databaseSchema,
                s.isDirectQueryMode,
                s.webhookStepComplete,
            ],
            (currentStep, isManualLinkingSelected, databaseSchema, isDirectQueryMode, webhookStepComplete): boolean => {
                if (isManualLinkingSelected && currentStep === 1) {
                    return false
                }

                if (!isManualLinkingSelected && currentStep === 3) {
                    if (databaseSchema.filter((n) => n.should_sync).length === 0) {
                        return false
                    }

                    if (isDirectQueryMode) {
                        return true
                    }

                    return databaseSchema.filter((n) => n.should_sync && !n.sync_type).length === 0
                }

                if (currentStep === 4) {
                    return webhookStepComplete
                }

                return true
            },
        ],
        showSkipButton: [
            (s) => [s.currentStep],
            (currentStep): boolean => {
                return currentStep === 5
            },
        ],
        nextButtonText: [
            (s) => [
                s.currentStep,
                s.isManualLinkingSelected,
                s.isDirectQueryMode,
                s.hasWebhookSchemas,
                (_, props) => props.onComplete,
                s.returnConfig,
            ],
            (
                currentStep,
                isManualLinkingSelected,
                isDirectQueryMode,
                hasWebhookSchemas,
                onComplete,
                returnConfig
            ): string => {
                if (currentStep === 3 && isManualLinkingSelected) {
                    return 'Link'
                }

                if (currentStep === 3) {
                    if (isDirectQueryMode) {
                        return 'Save tables'
                    }

                    if (hasWebhookSchemas) {
                        return 'Set up webhook'
                    }

                    return 'Import'
                }

                if (currentStep === 4) {
                    return 'Next'
                }

                if (currentStep === 5) {
                    if (onComplete) {
                        return 'Next'
                    }
                    if (returnConfig) {
                        return `Return to ${returnConfig.returnLabel}`
                    }
                    return 'Return to sources'
                }

                return 'Next'
            },
        ],
        showFooter: [
            (s) => [s.selectedConnector, s.isManualLinkFormVisible],
            (selectedConnector, isManualLinkFormVisible) => selectedConnector || isManualLinkFormVisible,
        ],
        connectors: [
            (s) => [s.dataWarehouseSources, s.availableSources],
            (sources, availableSources: Record<string, SourceConfig>): SourceConfig[] => {
                if (!availableSources) {
                    return []
                }
                return Object.values(availableSources).map((connector) => ({
                    ...connector,
                    disabledReason:
                        sources && sources.results.find((source) => source.source_type === connector.name)
                            ? 'Already linked'
                            : null,
                    existingSource:
                        sources && sources.results.find((source) => source.source_type === connector.name)
                            ? true
                            : false,
                }))
            },
        ],
        manualConnectors: [
            () => [],
            (): { name: string; type: ManualLinkSourceType }[] =>
                manualLinkSources.map((source) => ({
                    name: manualLinkSourceMap[source],
                    type: source,
                })),
        ],
        isSelfManagedSource: [
            (s) => [s.manualLinkingProvider],
            (manualLinkingProvider: ManualLinkSourceType | null): boolean => manualLinkingProvider !== null,
        ],
        tablesAllToggledOn: [
            (s) => [s.databaseSchema],
            (databaseSchema: ExternalDataSourceSyncSchema[]): boolean | 'indeterminate' => {
                const enabledCount = databaseSchema.filter((schema) => schema.should_sync).length
                const totalCount = databaseSchema.length
                return enabledCount === totalCount ? true : enabledCount > 0 ? 'indeterminate' : false
            },
        ],
        directQueryDefaultSchema: [
            (s) => [s.source],
            (source): string | null => (typeof source.payload.schema === 'string' ? source.payload.schema : null),
        ],
        groupedDirectQueryDatabaseSchema: [
            (s) => [s.databaseSchema, s.directQueryDefaultSchema],
            (databaseSchema, directQueryDefaultSchema) =>
                groupDirectQueryTablesBySchema(databaseSchema, directQueryDefaultSchema),
        ],
        groupedDirectQuerySchemaKeys: [
            (s) => [s.groupedDirectQueryDatabaseSchema],
            (groupedDirectQueryDatabaseSchema) =>
                getDefaultExpandedDirectQuerySchemaKeys(groupedDirectQueryDatabaseSchema),
        ],
        modalTitle: [
            (s) => [s.currentStep, s.isDirectQueryMode],
            (currentStep, isDirectQueryMode) => {
                if (currentStep === 1) {
                    return ''
                }
                if (currentStep === 2) {
                    return 'Link your data source'
                }

                if (currentStep === 3) {
                    return isDirectQueryMode ? 'Select tables to query' : 'Select tables to import'
                }

                if (currentStep === 4) {
                    return 'Set up webhook'
                }

                if (currentStep === 5) {
                    return isDirectQueryMode ? 'Tables ready to query' : 'Importing your data...'
                }

                return ''
            },
        ],
        // determines if the wizard is wrapped in another component
        isWrapped: [() => [(_, props) => props.onComplete], (onComplete) => !!onComplete],
    }),
    listeners(({ actions, values, props }) => ({
        verifyCdcSelfManagedSetupSuccess: ({ cdcSelfManagedVerifyResult }) => {
            if (cdcSelfManagedVerifyResult?.valid) {
                actions.closeCdcSelfManagedSetupDialog()
                actions.setIsLoading(true)
                actions.createSource()
                if (values.selectedConnector) {
                    posthog.capture('source created', { sourceType: values.selectedConnector.name })
                }
            }
        },
        closeCdcSelfManagedSetupDialog: () => {
            actions.clearCdcSelfManagedVerifyResult()
        },
        touchAllSourceConnectionDetailsFields: () => {
            // Walk the connector field tree and touch each leaf path so kea-forms
            // renders validation errors (matching the Next button behavior).
            const walk = (fields: any[], prefix: string): void => {
                for (const f of fields ?? []) {
                    if (!f?.name) {
                        continue
                    }
                    const p = prefix ? `${prefix}.${f.name}` : f.name
                    actions.touchSourceConnectionDetailsField(p)
                    if (Array.isArray(f.fields)) {
                        walk(f.fields, p)
                    }
                }
            }
            walk(values.selectedConnector?.fields ?? [], '')
            actions.touchSourceConnectionDetailsField('prefix')
        },
        setInitialConnector: () => {
            syncExpandedDirectQuerySchemaKeys(actions, values)
            actions.resetSourceForm()
        },
        resetSourceForm: ({ accessMethod }) => {
            const defaults = values.defaultSourceConnectionDetails
            const sourceConnectionDetails = values.sourceConnectionDetails as Record<string, unknown>
            const sourceKind = values.selectedConnector?.name?.toLowerCase()
            const savedValues = sourceKind ? restoreSourceFormState(sourceKind) : null
            const currentAccessMethod = accessMethod ?? sourceConnectionDetails?.access_method

            actions.resetSourceConnectionDetails(
                mergeRestoredSourceFormValues(defaults, savedValues, currentAccessMethod)
            )
        },
        setDatabaseSchemas: () => {
            syncExpandedDirectQuerySchemaKeys(actions, values)
        },
        updateSource: () => {
            syncExpandedDirectQuerySchemaKeys(actions, values)
        },
        toggleDirectQuerySchemaGroup: ({ schemaName, shouldSync }) => {
            actions.setDatabaseSchemas(
                values.databaseSchema.map((schema) => ({
                    ...schema,
                    should_sync:
                        splitDirectQueryTableName(schema.table, values.directQueryDefaultSchema).schemaName ===
                        schemaName
                            ? shouldSync
                            : schema.should_sync,
                }))
            )
            actions.setExpandedDirectQuerySchemaKeys(
                shouldSync
                    ? Array.from(new Set([...values.expandedDirectQuerySchemaKeys, schemaName]))
                    : values.expandedDirectQuerySchemaKeys.filter((key) => key !== schemaName)
            )
        },
        saveFormStateBeforeRedirect: () => {
            const sourceKind = values.selectedConnector?.name?.toLowerCase()
            if (sourceKind) {
                saveSourceFormState(sourceKind, values.sourceConnectionDetails as Record<string, unknown>)
            }
        },
        onBack: () => {
            if (values.currentStep <= 1) {
                actions.onClear()
            }
        },
        onClear: () => {
            actions.selectConnector(null)
            actions.resetSourceConnectionDetails()
            actions.clearSource()
            actions.toggleManualLinkFormVisible(false)
            actions.resetTable()
            actions.setIsLoading(false)
        },
        onSubmit: () => {
            // Shared function that triggers different actions depending on the current step
            if (values.currentStep === 1) {
                return
            }

            if (values.currentStep === 2 && values.selectedConnector?.name) {
                actions.submitSourceConnectionDetails()
            } else if (values.currentStep === 2 && values.isManualLinkFormVisible) {
                selfManagedSourceLogic.actions.submitTable()
                posthog.capture('source created', { sourceType: 'Manual' })
            }

            if (values.currentStep === 3 && values.selectedConnector?.name) {
                if (values.isDirectQueryMode) {
                    actions.updateSource({
                        payload: {
                            schemas: values.databaseSchema.map((schema) => ({
                                name: schema.table,
                                should_sync: schema.should_sync,
                                sync_type: null,
                                incremental_field: null,
                                incremental_field_type: null,
                                sync_time_of_day: null,
                                primary_key_columns: null,
                            })),
                        },
                    })
                    actions.setIsLoading(true)
                    actions.createSource()
                    if (values.selectedConnector) {
                        posthog.capture('source created', {
                            sourceType: values.selectedConnector.name,
                        })
                    }
                    return
                }

                const ignoredTables = values.databaseSchema.filter(
                    (schema) => !schema.should_sync || schema.sync_type === null
                )
                const cdcTables = values.databaseSchema.filter(
                    (schema) => schema.should_sync && schema.sync_type === 'cdc'
                )
                const webhookTables = values.databaseSchema.filter(
                    (schema) => schema.should_sync && schema.sync_type === 'webhook'
                )
                const appendOnlyTables = values.databaseSchema.filter(
                    (schema) => schema.should_sync && schema.sync_type === 'append'
                )
                const incrementalTables = values.databaseSchema.filter(
                    (schema) => schema.should_sync && schema.sync_type === 'incremental'
                )
                const fullRefreshTables = values.databaseSchema.filter(
                    (schema) => schema.should_sync && schema.sync_type === 'full_refresh'
                )

                const confirmation = (
                    <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-3 mt-2">
                        {/* CDC - Best */}
                        {cdcTables.length > 0 && (
                            <>
                                <div className="font-bold text-success">CDC</div>
                                <div>
                                    <span className="text-muted">{tableCountFormatter(cdcTables.length)}</span> —
                                    Real-time change capture via logical replication.
                                </div>
                            </>
                        )}

                        {/* Webhook - Best */}
                        {webhookTables.length > 0 && (
                            <>
                                <div className="font-bold text-success">Webhook</div>
                                <div>
                                    <span className="text-muted">{tableCountFormatter(webhookTables.length)}</span> —
                                    Real-time updates via webhooks.
                                </div>
                            </>
                        )}

                        {/* Incremental - Good */}
                        <div className="font-bold text-success">Incremental</div>
                        <div>
                            <span className="text-muted">
                                {tableCountFormatter(incrementalTables.length)}
                                {incrementalTables.length === 69 ? ' (nice)' : ''}
                                {incrementalTables.length === 67 ? ' (nice but only for genz)' : ''}
                            </span>{' '}
                            — Ideal. Syncs only changed rows using a field like{' '}
                            <span className="font-mono text-xs">updated_at</span>.
                        </div>

                        {/* Append-only - Caution */}
                        <div className="font-bold text-warning">Append-only</div>
                        <div>
                            <span className="text-muted">{tableCountFormatter(appendOnlyTables.length)}</span> — Use a
                            field that doesn't change on updates, like{' '}
                            <span className="font-mono text-xs">created_at</span>.
                        </div>

                        {/* Full refresh - Danger */}
                        <div className="font-bold text-danger">Full refresh</div>
                        <div>
                            <span className="text-muted">
                                {tableCountFormatter(fullRefreshTables.length, {
                                    none: 'None ✓',
                                })}
                            </span>{' '}
                            — Re-syncs all rows every time. Can significantly increase costs.
                        </div>

                        {/* Ignored - Muted */}
                        <div className="font-bold text-muted">Ignored</div>
                        <div>
                            <span className="text-muted">{tableCountFormatter(ignoredTables.length)}</span> — Tables
                            without sync configured will be skipped.
                        </div>
                    </div>
                )

                const sourcePayload = (values.source?.payload || {}) as Record<string, any>
                const cdcSelfManaged =
                    !!sourcePayload.cdc_enabled &&
                    sourcePayload.cdc_management_mode === 'self_managed' &&
                    cdcTables.length > 0

                LemonDialog.open({
                    title: 'Confirm your table configurations',
                    content: confirmation,
                    primaryButton: {
                        children: cdcSelfManaged ? 'Next: CDC setup SQL' : 'Confirm',
                        type: 'primary',
                        onClick: () => {
                            actions.updateSource({
                                payload: {
                                    schemas: values.databaseSchema.map((schema) => ({
                                        name: schema.table,
                                        should_sync: schema.should_sync,
                                        sync_type: schema.sync_type,
                                        incremental_field: schema.incremental_field,
                                        incremental_field_type: schema.incremental_field_type,
                                        sync_time_of_day: schema.sync_time_of_day,
                                        primary_key_columns: schema.primary_key_columns,
                                        ...(schema.sync_type === 'cdc' && schema.cdc_table_mode
                                            ? { cdc_table_mode: schema.cdc_table_mode }
                                            : {}),
                                    })),
                                },
                            })
                            if (cdcSelfManaged) {
                                // Show the setup SQL popup; user confirms → we verify → createSource fires
                                actions.openCdcSelfManagedSetupDialog()
                                return
                            }
                            actions.setIsLoading(true)
                            actions.createSource()
                            if (values.selectedConnector) {
                                posthog.capture('source created', {
                                    sourceType: values.selectedConnector.name,
                                })
                            }
                        },
                        size: 'small',
                    },
                    secondaryButton: {
                        children: 'Cancel',
                        type: 'tertiary',
                        size: 'small',
                    },
                })
            }

            if (values.currentStep === 4) {
                if (values.webhookResult?.success && (values.webhookResult.pending_inputs?.length ?? 0) === 0) {
                    actions.onNext()
                } else {
                    // Manual mode (or auto-create with pending inputs) — submit webhook form
                    // (validates, then triggers submitWebhookFields)
                    actions.submitWebhookFieldInputs()
                }
            }

            if (values.currentStep === 5) {
                if (props.onComplete) {
                    props.onComplete()
                } else {
                    actions.closeWizard()
                }
            }
        },
        createTableSuccess: () => {
            actions.cancelWizard()
        },
        closeWizard: () => {
            const returnUrl = values.returnConfig?.returnUrl
            actions.cancelWizard()
            router.actions.push(returnUrl ?? urls.sources())
        },
        cancelWizard: () => {
            actions.onClear()
            actions.clearSource()
            actions.loadSources()
            actions.resetSourceConnectionDetails()
        },
        createSource: async () => {
            if (values.selectedConnector === null) {
                // This should never happen
                return
            }

            try {
                const { id } = await api.externalDataSources.create({
                    ...values.source,
                    source_type: values.selectedConnector.name,
                })

                actions.setSourceId(id)
                actions.resetSourceConnectionDetails()
                actions.loadSources()
                actions.markTaskAsCompleted(SetupTaskId.ConnectSource)

                // When requiredTables is set (e.g. signals setup), skip step 4 and complete directly
                if (values.requiredTables && props.onComplete) {
                    props.onComplete()
                } else if (values.hasWebhookSchemas) {
                    // Go to webhook setup step (4)
                    actions.onNext()
                } else {
                    // Skip webhook step, go directly to progress (5)
                    actions.setStep(5)
                }
            } catch (e: any) {
                lemonToast.error(e.data?.message ?? e.message)
            } finally {
                actions.setIsLoading(false)
            }
        },
        createWebhook: async () => {
            if (!values.sourceId) {
                return
            }

            try {
                const result = await api.externalDataSources.createWebhook(values.sourceId)
                actions.setWebhookResult(result)
            } catch (e: any) {
                actions.setWebhookResult({
                    success: false,
                    webhook_url: '',
                    error: e.data?.message ?? e.message ?? 'Failed to create webhook',
                })
            }
        },
        submitWebhookFields: async () => {
            if (!values.sourceId) {
                return
            }

            const fieldValues = values.webhookFieldInputs
            if (Object.keys(fieldValues).length > 0) {
                try {
                    await api.externalDataSources.updateWebhookInputs(values.sourceId, fieldValues)
                } catch (e: any) {
                    lemonToast.error(e.data?.message ?? e.message ?? 'Failed to update webhook inputs')
                    return
                }
            }

            actions.onNext()
        },
        handleRedirect: async ({ source }) => {
            // By default, we assume the source is a valid external data source
            if (externalDataSources.includes(source)) {
                actions.updateSource({
                    source_type: source,
                })
            } else {
                lemonToast.error(`Something went wrong.`)
            }
        },
        submitSourceConnectionDetailsSuccess: () => {
            actions.getDatabaseSchemas()
        },
        getDatabaseSchemas: async () => {
            if (!values.selectedConnector) {
                return
            }

            actions.setIsLoading(true)

            try {
                const schemas = await api.externalDataSources.database_schema(
                    values.selectedConnector.name,
                    getDatabaseSchemaPayload(values.source)
                )

                let showToast = false

                for (const schema of schemas) {
                    if (values.isDirectQueryMode) {
                        schema.should_sync = true
                        schema.sync_type = null
                        continue
                    }

                    if (schema.sync_type === null) {
                        showToast = true
                        schema.should_sync = schema.should_sync_default ?? true

                        const cdcEnabled = values.source.payload?.cdc_enabled
                        if (cdcEnabled && schema.cdc_available) {
                            schema.sync_type = 'cdc'
                        } else if (schema.supports_webhooks) {
                            schema.sync_type = 'webhook'
                        } else if (schema.incremental_available || schema.append_available) {
                            const method = schema.incremental_available ? 'incremental' : 'append'
                            const resolvedField = resolveIncrementalField(schema.incremental_fields)
                            schema.sync_type = method
                            if (resolvedField) {
                                schema.incremental_field = resolvedField.field
                                schema.incremental_field_type = resolvedField.field_type
                            } else {
                                schema.sync_type = 'full_refresh'
                            }
                        } else {
                            schema.sync_type = 'full_refresh'
                        }
                    }
                }

                if (showToast && !values.requiredTables) {
                    lemonToast.info(
                        "We've setup some defaults for you! Please take a look to make sure you're happy with the results."
                    )
                }

                // If required tables are specified (e.g. signals setup), skip the schema selection step
                // entirely and create the source with only those tables, using their default sync settings
                if (values.requiredTables) {
                    const requiredSchemas = schemas.filter((schema) => values.requiredTables!.includes(schema.table))
                    if (requiredSchemas.length !== values.requiredTables.length) {
                        const missingTables = values.requiredTables.filter(
                            (table: string) => !requiredSchemas.some((schema) => schema.table === table)
                        )
                        lemonToast.error(`Required tables not found in source: ${missingTables.join(', ')}`)
                        actions.setIsLoading(false)
                        return
                    }

                    actions.updateSource({
                        payload: {
                            schemas: requiredSchemas.map((schema) => ({
                                name: schema.table,
                                should_sync: true,
                                sync_type: schema.sync_type,
                                incremental_field: schema.incremental_field,
                                incremental_field_type: schema.incremental_field_type,
                                sync_time_of_day: schema.sync_time_of_day ?? null,
                                primary_key_columns: schema.primary_key_columns,
                                ...(schema.sync_type === 'cdc' && schema.cdc_table_mode
                                    ? { cdc_table_mode: schema.cdc_table_mode }
                                    : {}),
                            })),
                        },
                    })
                    // Jump to step 3 so that createSource's onNext() advances to step 4 (sync progress)
                    actions.setStep(3)
                    actions.setIsLoading(true)
                    actions.createSource()
                    return
                }

                actions.setDatabaseSchemas(schemas)
                actions.onNext()
            } catch (e: any) {
                const errorMessage = e.data?.message ?? e.message
                lemonToast.error(errorMessage)

                posthog.capture('warehouse credentials invalid', {
                    sourceType: values.selectedConnector.name,
                    errorMessage,
                })
            }

            actions.setIsLoading(false)
        },
        setManualLinkingProvider: ({ provider }) => {
            actions.onNext()

            // Track marketing analytics intent for self-managed marketing sources
            if (provider && VALID_SELF_MANAGED_MARKETING_SOURCES.includes(provider)) {
                actions.addProductIntent({
                    product_type: ProductKey.MARKETING_ANALYTICS,
                    intent_context: ProductIntentContext.MARKETING_ANALYTICS_ADS_INTEGRATION_VISITED,
                })
            }
        },
        selectConnector: ({ connector, accessMethod }) => {
            syncExpandedDirectQuerySchemaKeys(actions, values)
            actions.resetSourceForm(accessMethod)

            actions.addProductIntent({
                product_type: ProductKey.DATA_WAREHOUSE,
                intent_context: ProductIntentContext.SELECTED_CONNECTOR,
            })

            // Track interest for marketing ad sources and marketing analytics
            const isNativeMarketingSource =
                connector?.name &&
                VALID_NATIVE_MARKETING_SOURCES.includes(
                    connector.name as (typeof VALID_NATIVE_MARKETING_SOURCES)[number]
                )
            const isExternalMarketingSource =
                connector?.name &&
                VALID_NON_NATIVE_MARKETING_SOURCES.includes(
                    connector.name as (typeof VALID_NON_NATIVE_MARKETING_SOURCES)[number]
                )

            if (isNativeMarketingSource || isExternalMarketingSource) {
                actions.addProductIntent({
                    product_type: ProductKey.MARKETING_ANALYTICS,
                    intent_context: ProductIntentContext.MARKETING_ANALYTICS_ADS_INTEGRATION_VISITED,
                })
            }
        },
        toggleAllTables: ({ selectAll }) => {
            actions.setDatabaseSchemas(
                values.databaseSchema.map((schema) => ({
                    ...schema,
                    should_sync: selectAll,
                }))
            )
        },
    })),
    urlToAction(({ actions, values }) => {
        const handleUrlChange = (_: Record<string, string | undefined>, searchParams: Record<string, string>): void => {
            const kind = searchParams.kind?.toLowerCase()
            const accessMethod = searchParams.access_method === 'direct' ? 'direct' : 'warehouse'
            const returnUrl = searchParams.returnUrl
            const returnLabel = searchParams.returnLabel

            if (returnUrl && returnLabel) {
                actions.setReturnConfig(returnUrl, returnLabel)
            } else {
                actions.clearReturnConfig()
            }

            const source = values.connectors?.find((s) => s?.name?.toLowerCase?.() === kind)
            const manualSource = values.manualConnectors?.find((s) => s?.type?.toLowerCase() === kind)

            if (manualSource) {
                actions.toggleManualLinkFormVisible(true)
                actions.setManualLinkingProvider(manualSource.type)
                return
            }

            if (source) {
                // selectConnector forwards accessMethod to `resetSourceForm`, which seeds the
                // connector's defaults and restores any OAuth-saved form state — saved
                // access_method wins over the URL one (the OAuth callback URL doesn't carry it).
                actions.selectConnector(source, accessMethod)
                actions.updateSource({ access_method: accessMethod })
                actions.handleRedirect(source.name)
                actions.setStep(2)
                return
            }

            if (values.currentStep <= 1) {
                actions.selectConnector(null)
                actions.setStep(1)
            }
        }

        return {
            [urls.dataWarehouseSourceNew()]: handleUrlChange,
        }
    }),

    forms(({ actions, values }) => ({
        sourceConnectionDetails: {
            // Real defaults come from the `defaultSourceConnectionDetails` selector and are
            // pushed into the form by the `resetSourceForm` listener. The cast widens the form's
            // inferred value type so call sites that read fields like `access_method`,
            // `payload.host`, `cdc_management_mode`, etc. still type-check.
            defaults: { prefix: '', description: '', payload: {} } as Record<string, any>,
            errors: (sourceValues) => {
                const selectedAccessMethod =
                    (sourceValues as Record<string, any>)?.access_method === 'direct' ? 'direct' : 'warehouse'
                const normalizedValues = {
                    ...(sourceValues as Record<string, any>),
                    access_method: selectedAccessMethod,
                }
                const errors = getErrorsForFields(values.selectedConnector?.fields ?? [], normalizedValues as any)

                if (values.sourceConnectionDetailsManualErrors.prefix && sourceValues.prefix) {
                    actions.setSourceConnectionDetailsManualErrors({
                        prefix: undefined,
                    })
                }

                return errors
            },
            submit: async (sourceValues) => {
                if (values.selectedConnector) {
                    const isDirectQueryMode =
                        values.selectedConnector.name === 'Postgres' && sourceValues.access_method === 'direct'
                    const payload: Record<string, any> = {
                        ...sourceValues,
                        access_method: isDirectQueryMode ? 'direct' : 'warehouse',
                        source_type: values.selectedConnector.name,
                    }
                    actions.setIsLoading(true)

                    try {
                        if (!isDirectQueryMode) {
                            await api.externalDataSources.source_prefix(payload.source_type, sourceValues.prefix)
                        }

                        const payloadKeys = (values.selectedConnector?.fields ?? []).map((n) => ({
                            name: n.name,
                            type: n.type,
                        }))

                        const fieldPayload: Record<string, any> = {
                            source_type: values.selectedConnector.name,
                        }

                        for (const { name, type } of payloadKeys) {
                            if (type === 'file-upload') {
                                try {
                                    // Assumes we're loading a JSON file
                                    const loadedFile: string = await new Promise((resolve, reject) => {
                                        const fileReader = new FileReader()
                                        fileReader.onload = (e) => resolve(e.target?.result as string)
                                        fileReader.onerror = (e) => reject(e)
                                        fileReader.readAsText(payload['payload'][name][0])
                                    })
                                    fieldPayload[name] = JSON.parse(loadedFile)
                                } catch {
                                    return lemonToast.error('File is not valid')
                                }
                            } else {
                                fieldPayload[name] = payload['payload'][name]
                            }
                        }

                        // Include CDC configuration if present
                        const cdcFields: Record<string, any> = {}
                        const cdcKeys = [
                            'cdc_enabled',
                            'cdc_management_mode',
                            'cdc_slot_name',
                            'cdc_publication_name',
                            'cdc_auto_drop_slot',
                            'cdc_lag_warning_threshold_mb',
                            'cdc_lag_critical_threshold_mb',
                        ]
                        for (const key of cdcKeys) {
                            if (payload['payload']?.[key] !== undefined) {
                                cdcFields[key] = payload['payload'][key]
                            }
                        }

                        // Only store the keys of the source type we're using
                        actions.updateSource({
                            ...payload,
                            payload: {
                                source_type: values.selectedConnector.name,
                                ...fieldPayload,
                                ...cdcFields,
                            },
                        })

                        actions.setIsLoading(false)
                    } catch (e: any) {
                        if (e?.data?.message) {
                            actions.setSourceConnectionDetailsManualErrors({
                                prefix: e.data.message,
                            })
                        }
                        actions.setIsLoading(false)

                        throw e
                    }
                }
            },
        },
        webhookFieldInputs: {
            defaults: {} as Record<string, any>,
            errors: (sourceValues) => {
                const webhookFields = values.selectedConnector?.webhookFields ?? []
                return getErrorsForFields(webhookFields, {
                    prefix: '',
                    payload: sourceValues as Record<string, any>,
                }).payload
            },
            submit: async () => {
                actions.submitWebhookFields()
            },
        },
    })),
])

export const getDatabaseSchemaPayload = (
    source: Pick<ExternalDataSourceCreatePayload, 'access_method' | 'payload'>
): Record<string, any> => ({
    ...source.payload,
    access_method: source.access_method ?? 'warehouse',
})

export const getErrorsForFields = (
    fields: SourceFieldConfig[],
    values:
        | {
              prefix: string
              payload: Record<string, any>
              access_method?: 'warehouse' | 'direct'
          }
        | undefined,
    options?: { allowBlankSensitiveFields?: boolean }
): Record<string, any> => {
    const errors: Record<string, any> = {
        payload: {},
    }

    const isDirectMode = values?.access_method === 'direct'

    if (isDirectMode) {
        if (!values?.prefix?.trim()) {
            errors['prefix'] = 'Please enter a name for this direct query source.'
        }
    } else if (!/^[a-zA-Z0-9_-]*$/.test(values?.prefix ?? '')) {
        errors['prefix'] = "Please enter a valid prefix (only letters, numbers, and '_' or '-')."
    }

    // Payload errors
    const validateField = (
        field: SourceFieldConfig,
        valueObj: Record<string, any>,
        errorsObj: Record<string, any>
    ): void => {
        if (field.type === 'switch-group') {
            // handle string value coming down from the backend for an update
            if (valueObj[field.name]?.['enabled'] && valueObj[field.name]?.['enabled'] !== 'False') {
                errorsObj[field.name] = {}
                field.fields.forEach((f) => validateField(f, valueObj[field.name], errorsObj[field.name]))
            }

            return
        }

        if (field.type === 'select') {
            const hasOptionFields = !!field.options.filter((n) => (n.fields?.length ?? 0) > 0).length

            if (!hasOptionFields) {
                if (field.required && !valueObj[field.name]) {
                    errorsObj[field.name] = `Please select a ${field.label.toLowerCase()}`
                }
            } else {
                errorsObj[field.name] = {}
                const selection = valueObj[field.name]?.['selection']
                field.options
                    .find((n) => n.value === selection)
                    ?.fields?.forEach((f) => validateField(f, valueObj[field.name], errorsObj[field.name]))
            }
            return
        }

        // All other types - check if required property exists on this field type
        if (
            options?.allowBlankSensitiveFields &&
            (('secret' in field && field.secret) || ('type' in field && field.type === 'password')) &&
            !valueObj[field.name]
        ) {
            return
        }

        if ('required' in field && field.required && !valueObj[field.name]) {
            errorsObj[field.name] = `Please enter a ${field.label.toLowerCase()}`
        }
    }

    for (const field of fields) {
        if (field.type === 'ssh-tunnel') {
            validateField(SSH_FIELD, values?.payload ?? {}, errors['payload'])
        } else {
            validateField(field, values?.payload ?? {}, errors['payload'])
        }
    }

    return errors
}

const tableCountFormatter = (
    count: number,
    { none = 'None', one = '1 table', many = 'tables' }: { none?: string; one?: string; many?: string } = {}
): string => {
    if (count === 0) {
        return none
    }

    if (count === 1) {
        return one
    }

    return `${count} ${many}`
}
