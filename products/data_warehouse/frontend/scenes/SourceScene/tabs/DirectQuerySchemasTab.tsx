import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonInput,
    LemonSkeleton,
    LemonSwitch,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { groupBy, pluralize } from 'lib/utils'
import { newInternalTab } from 'lib/utils/newInternalTab'

import { ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import { SourceEditorAction } from 'products/data_warehouse/frontend/shared/components/SourceEditorAction'
import { buildTableQueryUrl } from 'products/data_warehouse/frontend/utils'

import { sourceSettingsLogic } from './sourceSettingsLogic'

export function splitDirectQuerySchemaName(
    name: string,
    fallbackSchema?: string | null
): { schemaName: string; tableName: string } {
    const firstDotIndex = name.indexOf('.')

    if (firstDotIndex === -1) {
        const normalizedFallbackSchema = fallbackSchema?.trim()
        return {
            schemaName: normalizedFallbackSchema || 'Unqualified',
            tableName: name,
        }
    }

    return {
        schemaName: name.slice(0, firstDotIndex),
        tableName: name.slice(firstDotIndex + 1),
    }
}

export function groupDirectQuerySourceSchemasBySchema(
    schemas: ExternalDataSourceSchema[],
    fallbackSchema?: string | null
): { schemaName: string; schemas: ExternalDataSourceSchema[] }[] {
    return Object.entries(
        groupBy(
            schemas,
            (schema) => splitDirectQuerySchemaName(schema.table?.name ?? schema.name, fallbackSchema).schemaName
        )
    )
        .sort(([schemaA], [schemaB]) => schemaA.localeCompare(schemaB))
        .map(([schemaName, groupedSchemas]) => ({ schemaName, schemas: groupedSchemas }))
}

function getSchemaSelectionState(schemas: ExternalDataSourceSchema[]): boolean | 'indeterminate' {
    const enabledCount = schemas.filter((schema) => schema.should_sync).length

    if (enabledCount === 0) {
        return false
    }

    if (enabledCount === schemas.length) {
        return true
    }

    return 'indeterminate'
}

export interface DirectQuerySchemasTabProps {
    id: string
}

export function DirectQuerySchemasTab({ id }: DirectQuerySchemasTabProps): JSX.Element {
    const logic = sourceSettingsLogic({ id })
    const { source, sourceLoading, filteredSchemas, showEnabledSchemasOnly, schemaNameFilter, refreshingSchemas } =
        useValues(logic)
    const { setShowEnabledSchemasOnly, setSchemaNameFilter, refreshSchemas, updateSchema } = useActions(logic)

    const directQueryDefaultSchema = typeof source?.job_inputs?.schema === 'string' ? source.job_inputs.schema : null
    const groupedSchemas = groupDirectQuerySourceSchemasBySchema(filteredSchemas, directQueryDefaultSchema)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-3">
                    <LemonSwitch
                        checked={showEnabledSchemasOnly}
                        onChange={setShowEnabledSchemasOnly}
                        label="Show queryable only"
                    />
                    <LemonInput
                        type="search"
                        placeholder="Filter schemas"
                        size="small"
                        value={schemaNameFilter}
                        onChange={setSchemaNameFilter}
                    />
                    <span className="text-muted text-sm">{pluralize(groupedSchemas.length, 'schema', 'schemas')}</span>
                </div>
                <div className="flex items-center gap-2">
                    <SourceEditorAction source={source}>
                        <LemonButton
                            type="secondary"
                            loading={refreshingSchemas}
                            onClick={() => refreshSchemas()}
                            disabledReason={sourceLoading ? 'Source is loading' : undefined}
                        >
                            Pull new schemas
                        </LemonButton>
                    </SourceEditorAction>
                </div>
            </div>
            <DirectQuerySchemaGroups
                source={source}
                groupedSchemas={groupedSchemas}
                isLoading={sourceLoading}
                updateSchema={updateSchema}
            />
        </div>
    )
}

function DirectQuerySchemaGroups({
    source,
    groupedSchemas,
    isLoading,
    updateSchema,
}: {
    source: ExternalDataSource | null
    groupedSchemas: { schemaName: string; schemas: ExternalDataSourceSchema[] }[]
    isLoading: boolean
    updateSchema: (schema: ExternalDataSourceSchema) => void
}): JSX.Element {
    const [initialLoad, setInitialLoad] = useState(true)
    const groupedSchemaKeys = groupedSchemas.map((group) => group.schemaName)
    const groupedSchemaKeysFingerprint = groupedSchemaKeys.join('|')
    const [expandedSchemaKeys, setExpandedSchemaKeys] = useState<string[]>([])

    useEffect(() => {
        if (initialLoad && !isLoading) {
            setInitialLoad(false)
        }
    }, [isLoading, initialLoad])

    useEffect(() => {
        setExpandedSchemaKeys((currentKeys) => {
            const nextKeys = currentKeys.filter((key) => groupedSchemaKeys.includes(key))
            if (
                nextKeys.length > 0 &&
                nextKeys.length === currentKeys.length &&
                nextKeys.every((key, index) => key === currentKeys[index])
            ) {
                return currentKeys
            }
            if (nextKeys.length > 0) {
                return nextKeys
            }
            return groupedSchemaKeys
        })
    }, [groupedSchemaKeysFingerprint]) // oxlint-disable-line react-hooks/exhaustive-deps

    const directConnectionId = source?.id
    const getPreviewUrl = useCallback(
        (tableName: string): string => buildTableQueryUrl(tableName, directConnectionId),
        [directConnectionId]
    )

    const setDirectQuerySchemaEnabled = useCallback(
        (schema: ExternalDataSourceSchema, shouldSync: boolean) => {
            updateSchema({ ...schema, should_sync: shouldSync })
        },
        [updateSchema]
    )

    const toggleDirectQuerySchemaGroup = useCallback(
        (schemaName: string, shouldSync: boolean) => {
            const schemaGroup = groupedSchemas.find((group) => group.schemaName === schemaName)
            for (const schema of schemaGroup?.schemas ?? []) {
                setDirectQuerySchemaEnabled(schema, shouldSync)
            }
            setExpandedSchemaKeys((currentKeys) =>
                shouldSync
                    ? Array.from(new Set([...currentKeys, schemaName]))
                    : currentKeys.filter((key) => key !== schemaName)
            )
        },
        [groupedSchemas, setDirectQuerySchemaEnabled]
    )

    if (initialLoad) {
        return <LemonSkeleton className="h-48" />
    }

    if (groupedSchemas.length === 0) {
        return <div className="border rounded px-4 py-8 text-center text-muted-alt">No schemas found</div>
    }

    return (
        <div className="border rounded bg-bg-light">
            <LemonCollapse
                multiple
                embedded
                activeKeys={expandedSchemaKeys}
                onChange={setExpandedSchemaKeys}
                panels={groupedSchemas.map(({ schemaName, schemas }) => {
                    const selectedTablesCount = schemas.filter((schema) => schema.should_sync).length

                    return {
                        key: schemaName,
                        header: (
                            <div className="flex items-center justify-between gap-3 w-full">
                                <div className="flex items-center gap-2 min-w-0">
                                    <SourceEditorAction source={source}>
                                        <LemonCheckbox
                                            checked={getSchemaSelectionState(schemas)}
                                            stopPropagation
                                            onChange={(checked) => toggleDirectQuerySchemaGroup(schemaName, checked)}
                                        />
                                    </SourceEditorAction>
                                    <span className="font-semibold truncate">{schemaName}</span>
                                </div>
                                <span className="text-xs text-muted-alt whitespace-nowrap">
                                    {selectedTablesCount} of {schemas.length} tables queryable
                                </span>
                            </div>
                        ),
                        content: (
                            <div className="bg-bg-light">
                                {schemas.map((schema) => {
                                    const qualifiedName = schema.table?.name ?? schema.name
                                    const { tableName } = splitDirectQuerySchemaName(
                                        qualifiedName,
                                        typeof source?.job_inputs?.schema === 'string' ? source.job_inputs.schema : null
                                    )

                                    return (
                                        <div
                                            key={schema.id}
                                            className="grid grid-cols-[auto_minmax(0,1fr)] gap-2 px-6 py-1 items-center"
                                        >
                                            <SourceEditorAction source={source}>
                                                <LemonCheckbox
                                                    checked={schema.should_sync}
                                                    onChange={(active) => setDirectQuerySchemaEnabled(schema, active)}
                                                />
                                            </SourceEditorAction>
                                            <div className="flex items-center gap-1 min-w-0">
                                                {schema.should_sync ? (
                                                    <Link
                                                        to={getPreviewUrl(qualifiedName)}
                                                        className="truncate"
                                                        onClick={(event) => {
                                                            event.preventDefault()
                                                            newInternalTab(getPreviewUrl(qualifiedName))
                                                        }}
                                                    >
                                                        {tableName}
                                                    </Link>
                                                ) : (
                                                    <span className="truncate">{tableName}</span>
                                                )}
                                                {schema.description && (
                                                    <Tooltip title={schema.description}>
                                                        <IconInfo className="text-muted-alt text-base shrink-0" />
                                                    </Tooltip>
                                                )}
                                            </div>
                                        </div>
                                    )
                                })}
                            </div>
                        ),
                    }
                })}
            />
        </div>
    )
}
