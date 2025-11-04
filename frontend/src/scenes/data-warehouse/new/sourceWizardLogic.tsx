import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { IconWarning } from '@posthog/icons'
import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ActivationTask, activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import {
    ExternalDataSourceType,
    SourceConfig,
    SourceFieldConfig,
    SourceFieldSwitchGroupConfig,
    externalDataSources,
} from '~/queries/schema/schema-general'
import {
    Breadcrumb,
    ExternalDataSourceCreatePayload,
    ExternalDataSourceSyncSchema,
    IncrementalField,
    ManualLinkSourceType,
    ProductKey,
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
        updateSyncTimeOfDay: (schema: ExternalDataSourceSyncSchema, syncTimeOfDay: string) => ({
            schema,
            syncTimeOfDay,
        }),
        setIsProjectTime: (isProjectTime: boolean) => ({ isProjectTime }),
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
        ],
    })),
    reducers({
        tablesAllToggledOn: [
            true as boolean,
            {
                toggleAllTables: (_, { selectAll }) => selectAll,
            },
        ],
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
                updateSyncTimeOfDay: (state, { schema, syncTimeOfDay }) => {
                    return state.map((s) => ({
                        ...s,
                        sync_time_of_day: s.table === schema.table ? syncTimeOfDay : s.sync_time_of_day,
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
        isProjectTime: [
            false as boolean,
            {
                setIsProjectTime: (_, { isProjectTime }) => isProjectTime,
            },
        ],
    }),
    selectors({
        availableSources: [() => [(_, p) => p.availableSources], (availableSources) => availableSources],
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
                const maxTablesShownPerSection = 4
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
                    <>
                        <h4 className="mt-2">Full refresh tables</h4>
                        <div className={fullRefreshTables.length > 0 ? 'text-warning' : ''}>
                            {fullRefreshTables.length > 0 && <IconWarning />}
                            <span className={fullRefreshTables.length > 0 ? 'pl-2' : ''}>
                                Full refresh syncs can dramatically increase your spend if you aren't mindful of them.{' '}
                                {fullRefreshTables.length > 0 ? (
                                    <>You have the following tables setup for full refresh syncs:</>
                                ) : (
                                    <>None of your tables are setup for full refresh syncs. Yay!</>
                                )}
                            </span>
                        </div>
                        {fullRefreshTables.length > 0 && (
                            <>
                                <div className="px-4 grid grid-cols-1 gap-2 my-4 lg:grid-cols-2">
                                    {fullRefreshTables
                                        .slice(0, Math.min(fullRefreshTables.length, maxTablesShownPerSection))
                                        .map((table) => (
                                            <div
                                                key={table.table}
                                                className="font-mono px-2 rounded bg-surface-secondary w-min"
                                            >
                                                {table.table}
                                            </div>
                                        ))}
                                </div>
                                <div>
                                    {fullRefreshTables.length > maxTablesShownPerSection && (
                                        <div className="my-4">
                                            and{' '}
                                            <span className="text-warning font-bold">
                                                {fullRefreshTables.length - maxTablesShownPerSection}
                                            </span>{' '}
                                            more...
                                        </div>
                                    )}
                                </div>
                            </>
                        )}
                        <h4 className="mt-2">Append-only tables</h4>
                        <div>
                            Append-only syncs, while preferrable to full refresh syncs, still need to be configured with
                            care. The field you select for append-only syncing should not change when a row is updated
                            &ndash; for example, <span className="font-mono">created_at</span>.{' '}
                            {appendOnlyTables.length > 0 ? (
                                <>You have the following tables setup for append-only syncs:</>
                            ) : (
                                <>None of your tables are setup for append-only syncs. Sick!</>
                            )}
                        </div>
                        {appendOnlyTables.length > 0 && (
                            <>
                                <div className="px-4 grid grid-cols-1 gap-2 my-4 lg:grid-cols-2">
                                    {appendOnlyTables
                                        .slice(0, Math.min(appendOnlyTables.length, maxTablesShownPerSection))
                                        .map((table) => (
                                            <div
                                                key={table.table}
                                                className="font-mono px-2 rounded bg-surface-secondary w-min"
                                            >
                                                {table.table}
                                            </div>
                                        ))}
                                </div>
                                <div>
                                    {appendOnlyTables.length > maxTablesShownPerSection && (
                                        <div className="my-4">
                                            and{' '}
                                            <span className="text-warning font-bold">
                                                {appendOnlyTables.length - maxTablesShownPerSection}
                                            </span>{' '}
                                            more...
                                        </div>
                                    )}
                                </div>
                            </>
                        )}
                        <h4 className="mt-2">Ignored tables</h4>
                        <div>
                            If you do not enable the checkbox for a table or configure its sync method, it will be
                            ignored.{' '}
                            {ignoredTables.length > 0 ? (
                                <>
                                    You currently have{' '}
                                    <span className="text-warning font-bold">{ignoredTables.length}</span> table(s) set
                                    to be ignored from future syncs.
                                </>
                            ) : (
                                <>You are syncing all of your tables. You'll be bathing in data soon.</>
                            )}
                        </div>
                        <h4 className="mt-2">Incremental tables</h4>
                        <div>
                            The remainder of your tables are setup for incremental syncs, which are typically ideal. The
                            field you select for syncing incrementally should change each time the row is updated - for
                            example, <span className="font-mono">updated_at</span>.{' '}
                            {incrementalTables.length > 0 && (
                                <>
                                    You currently have{' '}
                                    <span className="text-warning font-bold">
                                        {incrementalTables.length} {incrementalTables.length === 69 && ' (nice)'}
                                    </span>{' '}
                                    table(s) set to sync incrementally.
                                </>
                            )}
                        </div>
                    </>
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

                activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.ConnectSource)

                actions.setSourceId(id)
                actions.resetSourceConnectionDetails()
                actions.loadSources(null)
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
        setManualLinkingProvider: () => {
            actions.onNext()
        },
        selectConnector: () => {
            actions.addProductIntent({
                product_type: ProductKey.DATA_WAREHOUSE,
                intent_context: ProductIntentContext.SELECTED_CONNECTOR,
            })
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
