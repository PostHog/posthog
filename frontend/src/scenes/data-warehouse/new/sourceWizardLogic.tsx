import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import {
    VALID_NON_NATIVE_MARKETING_SOURCES,
    VALID_SELF_MANAGED_MARKETING_SOURCES,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { ActivationTask, activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
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

import { dataWarehouseSettingsLogic } from '../settings/dataWarehouseSettingsLogic'
import { dataWarehouseTableLogic } from './dataWarehouseTableLogic'
import type { sourceWizardLogicType } from './sourceWizardLogicType'

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
        },
        {
            name: 'port',
            label: 'Tunnel port',
            type: 'number',
            required: true,
            placeholder: '22',
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
                        },
                        {
                            name: 'password',
                            label: 'Tunnel password',
                            type: 'password',
                            required: true,
                            placeholder: '',
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
                        },
                        {
                            name: 'private_key',
                            label: 'Tunnel private key',
                            type: 'textarea',
                            required: true,
                            placeholder: '',
                        },
                        {
                            name: 'passphrase',
                            label: 'Tunnel passphrase',
                            type: 'password',
                            required: false,
                            placeholder: '',
                        },
                    ],
                },
            ],
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
        { prefix: '', payload: {} } as Record<string, any>
    )
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

export interface SourceWizardLogicProps {
    onComplete?: () => void
    availableSources: Record<string, SourceConfig>
}

export const sourceWizardLogic = kea<sourceWizardLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'sourceWizardLogic']),
    props({} as SourceWizardLogicProps),
    actions({
        selectConnector: (connector: SourceConfig | null) => ({ connector }),
        setInitialConnector: (connector: SourceConfig | null) => ({ connector }),
        toggleManualLinkFormVisible: (visible: boolean) => ({ visible }),
        handleRedirect: (source: ExternalDataSourceType, searchParams?: any) => ({ source, searchParams }),
        onClear: true,
        onBack: true,
        onNext: true,
        onSubmit: true,
        setDatabaseSchemas: (schemas: ExternalDataSourceSyncSchema[]) => ({ schemas }),
        toggleSchemaShouldSync: (schema: ExternalDataSourceSyncSchema, shouldSync: boolean) => ({ schema, shouldSync }),
        updateSchemaSyncType: (
            schema: ExternalDataSourceSyncSchema,
            syncType: ExternalDataSourceSyncSchema['sync_type'],
            incrementalField: string | null,
            incrementalFieldType: string | null
        ) => ({
            schema,
            syncType,
            incrementalField,
            incrementalFieldType,
        }),
        clearSource: true,
        updateSource: (source: Partial<ExternalDataSourceCreatePayload>) => ({ source }),
        createSource: true,
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setSourceId: (id: string) => ({ sourceId: id }),
        closeWizard: true,
        cancelWizard: true,
        setStep: (step: number) => ({ step }),
        getDatabaseSchemas: true,
        setManualLinkingProvider: (provider: ManualLinkSourceType) => ({ provider }),
        openSyncMethodModal: (schema: ExternalDataSourceSyncSchema) => ({ schema }),
        cancelSyncMethodModal: true,
        toggleAllTables: (selectAll: boolean) => ({ selectAll }),
    }),
    connect(() => ({
        values: [
            dataWarehouseTableLogic,
            ['tableLoading'],
            dataWarehouseSettingsLogic,
            ['dataWarehouseSources'],
            preflightLogic,
            ['preflight'],
        ],
        actions: [
            dataWarehouseTableLogic,
            ['resetTable', 'createTableSuccess'],
            dataWarehouseSettingsLogic,
            ['loadSources'],
            teamLogic,
            ['addProductIntent'],
            activationLogic,
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
                toggleSchemaShouldSync: (state, { schema, shouldSync }) => {
                    return state.map((s) => ({
                        ...s,
                        should_sync: s.table === schema.table ? shouldSync : s.should_sync,
                    }))
                },
                updateSchemaSyncType: (state, { schema, syncType, incrementalField, incrementalFieldType }) => {
                    return state.map((s) => ({
                        ...s,
                        sync_type: s.table === schema.table ? syncType : s.sync_type,
                        incremental_field: s.table === schema.table ? incrementalField : s.incremental_field,
                        incremental_field_type:
                            s.table === schema.table ? incrementalFieldType : s.incremental_field_type,
                    }))
                },
            },
        ],
        source: [
            { payload: {}, prefix: '' } as {
                prefix: string
                payload: Record<string, any>
            },
            {
                updateSource: (state, { source }) => {
                    return {
                        prefix: source.prefix ?? state.prefix,
                        payload: {
                            ...state.payload,
                            ...source.payload,
                        },
                    }
                },
                clearSource: () => ({ payload: {}, prefix: '' }),
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
                updateSchemaSyncType: (_, { schema, syncType, incrementalField, incrementalFieldType }) => ({
                    ...schema,
                    sync_type: syncType,
                    incremental_field: incrementalField,
                    incremental_field_type: incrementalFieldType,
                }),
            },
        ],
    }),
    selectors({
        availableSources: [() => [(_, p) => p.availableSources], (availableSources) => availableSources],
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
                        key: Scene.DataPipelines,
                        name: 'Data pipelines',
                        path: urls.dataPipelines('overview'),
                        iconType: 'data_pipeline',
                    },
                    {
                        key: [Scene.DataPipelines, 'sources'],
                        name: `Sources`,
                        path: urls.dataPipelines('sources'),
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

        isManualLinkingSelected: [(s) => [s.selectedConnector], (selectedConnector): boolean => !selectedConnector],
        canGoBack: [
            (s) => [s.currentStep],
            (currentStep): boolean => {
                return currentStep !== 4
            },
        ],
        canGoNext: [
            (s) => [s.currentStep, s.isManualLinkingSelected, s.databaseSchema],
            (currentStep, isManualLinkingSelected, databaseSchema): boolean => {
                if (isManualLinkingSelected && currentStep === 1) {
                    return false
                }

                if (!isManualLinkingSelected && currentStep === 3) {
                    if (databaseSchema.filter((n) => n.should_sync).length === 0) {
                        return false
                    }

                    return databaseSchema.filter((n) => n.should_sync && !n.sync_type).length === 0
                }

                return true
            },
        ],
        showSkipButton: [
            (s) => [s.currentStep],
            (currentStep): boolean => {
                return currentStep === 4
            },
        ],
        nextButtonText: [
            (s) => [s.currentStep, s.isManualLinkingSelected, (_, props) => props.onComplete],
            (currentStep, isManualLinkingSelected, onComplete): string => {
                if (currentStep === 3 && isManualLinkingSelected) {
                    return 'Link'
                }

                if (currentStep === 3) {
                    return 'Import'
                }

                if (currentStep === 4) {
                    if (onComplete) {
                        return 'Next'
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
        tablesAllToggledOn: [
            (s) => [s.databaseSchema],
            (databaseSchema: ExternalDataSourceSyncSchema[]): boolean | 'indeterminate' => {
                const enabledCount = databaseSchema.filter((schema) => schema.should_sync).length
                const totalCount = databaseSchema.length
                return enabledCount === totalCount ? true : enabledCount > 0 ? 'indeterminate' : false
            },
        ],
        modalTitle: [
            (s) => [s.currentStep],
            (currentStep) => {
                if (currentStep === 1) {
                    return ''
                }
                if (currentStep === 2) {
                    return 'Link your data source'
                }

                if (currentStep === 3) {
                    return 'Select tables to import'
                }

                if (currentStep === 4) {
                    return 'Importing your data...'
                }

                return ''
            },
        ],
        // determines if the wizard is wrapped in another component
        isWrapped: [() => [(_, props) => props.onComplete], (onComplete) => !!onComplete],
    }),
    listeners(({ actions, values, props }) => ({
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
                dataWarehouseTableLogic.actions.submitTable()
                posthog.capture('source created', { sourceType: 'Manual' })
            }

            if (values.currentStep === 3 && values.selectedConnector?.name) {
                const ignoredTables = values.databaseSchema.filter(
                    (schema) => !schema.should_sync || schema.sync_type === null
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
                                {tableCountFormatter(fullRefreshTables.length, { none: 'None ✓' })}
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

                LemonDialog.open({
                    title: 'Confirm your table configurations',
                    content: confirmation,
                    primaryButton: {
                        children: 'Confirm',
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
                                    })),
                                },
                            })
                            actions.setIsLoading(true)
                            actions.createSource()
                            if (values.selectedConnector) {
                                posthog.capture('source created', { sourceType: values.selectedConnector.name })
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
            actions.cancelWizard()
            router.actions.push(urls.dataPipelines('sources'))
        },
        cancelWizard: () => {
            actions.onClear()
            actions.clearSource()
            actions.loadSources(null)
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

                lemonToast.success('New data resource created')

                actions.setSourceId(id)
                actions.resetSourceConnectionDetails()
                actions.loadSources(null)
                actions.markTaskAsCompleted(ActivationTask.ConnectSource)
                actions.onNext()
            } catch (e: any) {
                lemonToast.error(e.data?.message ?? e.message)
            } finally {
                actions.setIsLoading(false)
            }
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
                    values.source.payload ?? {}
                )

                let showToast = false

                for (const schema of schemas) {
                    if (schema.sync_type === null) {
                        showToast = true
                        schema.should_sync = true

                        // Use incremental if available
                        if (schema.incremental_available || schema.append_available) {
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

                if (showToast) {
                    lemonToast.info(
                        "We've setup some defaults for you! Please take a look to make sure you're happy with the results."
                    )
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
        selectConnector: ({ connector }) => {
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
            const source = values.connectors?.find((s) => s?.name?.toLowerCase?.() === kind)
            const manualSource = values.manualConnectors?.find((s) => s?.type?.toLowerCase() === kind)

            if (manualSource) {
                actions.toggleManualLinkFormVisible(true)
                actions.setManualLinkingProvider(manualSource.type)
                return
            }

            if (source) {
                actions.selectConnector(source)
                actions.handleRedirect(source.name)
                actions.setStep(2)
                return
            }

            actions.selectConnector(null)
            actions.setStep(1)
        }

        return {
            [urls.dataWarehouseSourceNew()]: handleUrlChange,
        }
    }),

    forms(({ actions, values, props }) => ({
        sourceConnectionDetails: {
            defaults: buildKeaFormDefaultFromSourceDetails(props.availableSources),
            errors: (sourceValues) => {
                const errors = getErrorsForFields(values.selectedConnector?.fields ?? [], sourceValues as any)

                if (values.sourceConnectionDetailsManualErrors.prefix && sourceValues.prefix) {
                    actions.setSourceConnectionDetailsManualErrors({
                        prefix: undefined,
                    })
                }

                return errors
            },
            submit: async (sourceValues) => {
                if (values.selectedConnector) {
                    const payload: Record<string, any> = {
                        ...sourceValues,
                        source_type: values.selectedConnector.name,
                    }
                    actions.setIsLoading(true)

                    try {
                        await api.externalDataSources.source_prefix(payload.source_type, sourceValues.prefix)

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

                        // Only store the keys of the source type we're using
                        actions.updateSource({
                            ...payload,
                            payload: {
                                source_type: values.selectedConnector.name,
                                ...fieldPayload,
                            },
                        })

                        actions.setIsLoading(false)
                    } catch (e: any) {
                        if (e?.data?.message) {
                            actions.setSourceConnectionDetailsManualErrors({ prefix: e.data.message })
                        }
                        actions.setIsLoading(false)

                        throw e
                    }
                }
            },
        },
    })),
])

export const getErrorsForFields = (
    fields: SourceFieldConfig[],
    values: { prefix: string; payload: Record<string, any> } | undefined
): Record<string, any> => {
    const errors: Record<string, any> = {
        payload: {},
    }

    // Prefix errors
    if (!/^[a-zA-Z0-9_-]*$/.test(values?.prefix ?? '')) {
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
