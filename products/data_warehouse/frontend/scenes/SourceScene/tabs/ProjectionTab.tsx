import { BuiltLogic, useActions, useValues } from 'kea'
import React, { useEffect, useState } from 'react'

import {
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonInput,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { AccessControlAction, AccessControlActionChildrenProps } from 'lib/components/AccessControlAction'
import { dayjs } from 'lib/dayjs'

import { AccessControlLevel, AccessControlResourceType, ExternalDataSource } from '~/types'

import { projectionEditorLogic, ProjectionEditorLogicProps } from './projectionEditorLogic'
import type { projectionEditorLogicType } from './projectionEditorLogicType'
import {
    ExternalDataSourceSchemaWithProjectionMetadata,
    ExternalDataSourceWithProjectionMetadata,
    getRawProjectionSchemaMetadata,
} from './projectionTypes'

const SourceEditorAction = ({
    source,
    children,
}: {
    source: ExternalDataSource | null
    children:
        | React.ComponentType<AccessControlActionChildrenProps>
        | React.ReactElement<AccessControlActionChildrenProps>
}): JSX.Element => (
    <AccessControlAction
        resourceType={AccessControlResourceType.ExternalDataSource}
        minAccessLevel={AccessControlLevel.Editor}
        userAccessLevel={source?.user_access_level}
    >
        {children}
    </AccessControlAction>
)

function getSourceTableLabel(schema: ExternalDataSourceSchemaWithProjectionMetadata): string {
    const rawMetadata = getRawProjectionSchemaMetadata(schema)
    const sourceSchema = rawMetadata?.source_schema
    const sourceTableName = rawMetadata?.source_table_name

    if (sourceSchema && sourceTableName) {
        return `${sourceSchema}.${sourceTableName}`
    }

    return schema.name
}

export function ProjectionTab({ id, tabId }: ProjectionEditorLogicProps): JSX.Element {
    const logic = projectionEditorLogic({ id, tabId })
    const {
        source,
        sourceLoading,
        projectionSource,
        projectionSchemas,
        draftTables,
        projectionRevisions,
        projectionRevisionsLoading,
        activeProjectionRevision,
        isProjectionDirty,
        projectionSaving,
        activatingRevisionId,
    } = useValues(logic)
    const { syncProjectionState, resetProjectionDrafts, setDraftEnabled, saveProjection, activateRevision } =
        useActions(logic)
    const [expandedSchemaIds, setExpandedSchemaIds] = useState<string[]>([])
    const allSchemaIds = projectionSchemas.map((schema) => schema.id)
    const allSchemasExpanded =
        allSchemaIds.length > 0 && allSchemaIds.every((schemaId) => expandedSchemaIds.includes(schemaId))
    const allSchemasSelected =
        allSchemaIds.length > 0 && projectionSchemas.every((schema) => draftTables[schema.id]?.enabled ?? false)

    useEffect(() => {
        syncProjectionState((projectionSource as ExternalDataSourceWithProjectionMetadata | null) ?? null)
    }, [projectionSource, syncProjectionState])

    useEffect(() => {
        if (!projectionSchemas.length) {
            return
        }

        setExpandedSchemaIds((currentIds) => {
            const validIds = currentIds.filter((id) => projectionSchemas.some((schema) => schema.id === id))
            if (validIds.length === currentIds.length && validIds.every((id, index) => id === currentIds[index])) {
                return currentIds
            }

            return validIds
        })
    }, [projectionSchemas])

    if (sourceLoading && !projectionSchemas.length) {
        return <LemonSkeleton className="h-96" />
    }

    if (!projectionSchemas.length) {
        return (
            <div className="border rounded bg-bg-light px-4 py-8 text-center text-muted-alt">
                Projection editing becomes available once source tables have been discovered for this connection.
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div className="border rounded bg-bg-light p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <div className="font-semibold">
                            {activeProjectionRevision
                                ? `Active revision v${activeProjectionRevision.version}`
                                : 'Passthrough'}
                        </div>
                        <div className="text-sm text-muted-alt max-w-3xl">
                            Projections rename tables, hide raw columns, add custom fields, and add foreign keys on top
                            of the direct Postgres connection. When no revision is active, the source passes through
                            as-is.
                        </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <SourceEditorAction source={source}>
                            <LemonButton
                                type="secondary"
                                disabledReason={!isProjectionDirty ? 'No unsaved changes' : undefined}
                                onClick={resetProjectionDrafts}
                            >
                                Reset to active
                            </LemonButton>
                        </SourceEditorAction>
                        <SourceEditorAction source={source}>
                            <LemonButton
                                type="secondary"
                                loading={projectionSaving}
                                onClick={() => saveProjection(false)}
                            >
                                Save revision
                            </LemonButton>
                        </SourceEditorAction>
                        <SourceEditorAction source={source}>
                            <LemonButton type="primary" loading={projectionSaving} onClick={() => saveProjection(true)}>
                                Save and activate
                            </LemonButton>
                        </SourceEditorAction>
                    </div>
                </div>
                <div className="mt-4 space-y-2">
                    <div className="text-xs font-semibold uppercase tracking-wide text-muted-alt">Revision history</div>
                    {projectionRevisionsLoading ? (
                        <LemonSkeleton className="h-20" />
                    ) : projectionRevisions.length === 0 ? (
                        <div className="text-sm text-muted-alt">
                            No saved revisions yet. The current state is passthrough.
                        </div>
                    ) : (
                        <div className="space-y-2">
                            {projectionRevisions.map((revision) => (
                                <div
                                    key={revision.id}
                                    className="flex flex-wrap items-center justify-between gap-2 rounded border bg-bg-3000 px-3 py-2"
                                >
                                    <div className="flex items-center gap-2">
                                        <span className="font-medium">v{revision.version}</span>
                                        {revision.is_active && <LemonTag type="success">Active</LemonTag>}
                                        <span className="text-sm text-muted-alt">
                                            {dayjs(revision.created_at).format('MMM D, YYYY HH:mm')}
                                            {revision.created_by ? ` by ${revision.created_by}` : ''}
                                        </span>
                                    </div>
                                    {!revision.is_active && (
                                        <SourceEditorAction source={source}>
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                loading={activatingRevisionId === revision.id}
                                                onClick={() => activateRevision(revision.id)}
                                            >
                                                Activate
                                            </LemonButton>
                                        </SourceEditorAction>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            <div className="flex flex-wrap justify-end gap-2">
                <SourceEditorAction source={source}>
                    <LemonButton
                        type="secondary"
                        size="small"
                        disabledReason={allSchemasSelected ? 'All tables are already queryable' : undefined}
                        onClick={() => projectionSchemas.forEach((schema) => setDraftEnabled(schema.id, true))}
                    >
                        Select all
                    </LemonButton>
                </SourceEditorAction>
                <SourceEditorAction source={source}>
                    <LemonButton
                        type="secondary"
                        size="small"
                        disabledReason={!allSchemasSelected ? 'Not all tables are queryable' : undefined}
                        onClick={() => projectionSchemas.forEach((schema) => setDraftEnabled(schema.id, false))}
                    >
                        Unselect all
                    </LemonButton>
                </SourceEditorAction>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => setExpandedSchemaIds(allSchemasExpanded ? [] : allSchemaIds)}
                >
                    {allSchemasExpanded ? 'Collapse all' : 'Expand all'}
                </LemonButton>
            </div>

            <LemonCollapse
                multiple
                embedded
                activeKeys={expandedSchemaIds}
                onChange={(keys) => setExpandedSchemaIds(keys as string[])}
                panels={projectionSchemas.map((schema) => {
                    const draft = draftTables[schema.id]
                    const rawColumns = getRawProjectionSchemaMetadata(schema)?.columns ?? []
                    const removedFields = new Set(draft?.removed_fields ?? [])
                    const remainingFieldCount = rawColumns.filter((column) => !removedFields.has(column.name)).length

                    return {
                        key: schema.id,
                        header: (
                            <div className="flex flex-wrap items-center justify-between gap-3 w-full">
                                <div className="min-w-0">
                                    <div className="font-semibold truncate">{draft?.query_name || schema.name}</div>
                                    <div className="text-xs text-muted-alt truncate">{getSourceTableLabel(schema)}</div>
                                </div>
                                <div className="flex items-center gap-3 text-xs text-muted-alt">
                                    <span>
                                        {remainingFieldCount} fields
                                        {draft?.custom_fields?.length ? ` + ${draft.custom_fields.length} custom` : ''}
                                    </span>
                                    <div
                                        onClick={(event) => event.stopPropagation()}
                                        onMouseDown={(event) => event.stopPropagation()}
                                        onKeyDown={(event) => event.stopPropagation()}
                                    >
                                        <SourceEditorAction source={source}>
                                            <LemonSwitch
                                                checked={draft?.enabled ?? false}
                                                onChange={(enabled) => setDraftEnabled(schema.id, enabled)}
                                                label="Queryable"
                                            />
                                        </SourceEditorAction>
                                    </div>
                                </div>
                            </div>
                        ),
                        content: <ProjectionSchemaEditor logic={logic} schema={schema} source={source} />,
                    }
                })}
            />
        </div>
    )
}

function ProjectionSchemaEditor({
    logic,
    schema,
    source,
}: {
    logic: BuiltLogic<projectionEditorLogicType>
    schema: ExternalDataSourceSchemaWithProjectionMetadata
    source: ExternalDataSource | null
}): JSX.Element {
    const { draftTables } = useValues(logic)
    const {
        setDraftQueryName,
        toggleRemovedField,
        addCustomField,
        updateCustomField,
        removeCustomField,
        addForeignKey,
        updateForeignKey,
        removeForeignKey,
    } = useActions(logic)
    const draft = draftTables[schema.id]
    const rawColumns = getRawProjectionSchemaMetadata(schema)?.columns ?? []
    const removedFields = new Set(draft?.removed_fields ?? [])

    if (!draft) {
        return <div className="px-4 py-3 text-sm text-muted-alt">Projection state is loading.</div>
    }

    return (
        <div className="space-y-4 bg-bg-light px-4 py-4">
            <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <div>
                    <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-alt">
                        Projected table name
                    </div>
                    <SourceEditorAction source={source}>
                        <LemonInput
                            value={draft.query_name}
                            onChange={(value) => setDraftQueryName(schema.id, value)}
                            placeholder="analytics.users"
                        />
                    </SourceEditorAction>
                </div>
                <div className="text-sm text-muted-alt">
                    Raw table: <code>{getSourceTableLabel(schema)}</code>
                </div>
            </div>

            <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-alt">Fields</div>
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {rawColumns.map((column) => (
                        <SourceEditorAction source={source} key={column.name}>
                            <LemonCheckbox
                                checked={!removedFields.has(column.name)}
                                onChange={() => toggleRemovedField(schema.id, column.name)}
                                label={
                                    <span className="flex items-center gap-2">
                                        <code>{column.name}</code>
                                        <span className="text-xs text-muted-alt">{column.data_type}</span>
                                    </span>
                                }
                            />
                        </SourceEditorAction>
                    ))}
                </div>
            </div>

            <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="text-xs font-semibold uppercase tracking-wide text-muted-alt">Custom fields</div>
                    <SourceEditorAction source={source}>
                        <LemonButton type="secondary" size="small" onClick={() => addCustomField(schema.id)}>
                            Add custom field
                        </LemonButton>
                    </SourceEditorAction>
                </div>
                <div className="space-y-3">
                    {draft.custom_fields.length === 0 ? (
                        <div className="text-sm text-muted-alt">No custom fields.</div>
                    ) : (
                        draft.custom_fields.map((field, index) => (
                            <div key={`${schema.id}-custom-${index}`} className="rounded border bg-bg-3000 p-3">
                                <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]">
                                    <SourceEditorAction source={source}>
                                        <LemonInput
                                            value={field.name}
                                            onChange={(value) => updateCustomField(schema.id, index, 'name', value)}
                                            placeholder="full_name"
                                        />
                                    </SourceEditorAction>
                                    <SourceEditorAction source={source}>
                                        <LemonTextArea
                                            value={field.expression}
                                            onChange={(value) =>
                                                updateCustomField(schema.id, index, 'expression', value)
                                            }
                                            placeholder="concat(first_name, ' ', last_name)"
                                            rows={2}
                                        />
                                    </SourceEditorAction>
                                    <SourceEditorAction source={source}>
                                        <LemonButton
                                            status="danger"
                                            type="secondary"
                                            size="small"
                                            onClick={() => removeCustomField(schema.id, index)}
                                        >
                                            Remove
                                        </LemonButton>
                                    </SourceEditorAction>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="text-xs font-semibold uppercase tracking-wide text-muted-alt">Foreign keys</div>
                    <SourceEditorAction source={source}>
                        <LemonButton type="secondary" size="small" onClick={() => addForeignKey(schema.id)}>
                            Add foreign key
                        </LemonButton>
                    </SourceEditorAction>
                </div>
                <div className="space-y-3">
                    {draft.foreign_keys.length === 0 ? (
                        <div className="text-sm text-muted-alt">No foreign keys.</div>
                    ) : (
                        draft.foreign_keys.map((field, index) => (
                            <div key={`${schema.id}-foreign-${index}`} className="rounded border bg-bg-3000 p-3">
                                <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
                                    <SourceEditorAction source={source}>
                                        <LemonInput
                                            value={field.column}
                                            onChange={(value) => updateForeignKey(schema.id, index, 'column', value)}
                                            placeholder="person_id"
                                        />
                                    </SourceEditorAction>
                                    <SourceEditorAction source={source}>
                                        <LemonInput
                                            value={field.target_table}
                                            onChange={(value) =>
                                                updateForeignKey(schema.id, index, 'target_table', value)
                                            }
                                            placeholder="persons"
                                        />
                                    </SourceEditorAction>
                                    <SourceEditorAction source={source}>
                                        <LemonInput
                                            value={field.target_column}
                                            onChange={(value) =>
                                                updateForeignKey(schema.id, index, 'target_column', value)
                                            }
                                            placeholder="id"
                                        />
                                    </SourceEditorAction>
                                    <SourceEditorAction source={source}>
                                        <LemonButton
                                            status="danger"
                                            type="secondary"
                                            size="small"
                                            onClick={() => removeForeignKey(schema.id, index)}
                                        >
                                            Remove
                                        </LemonButton>
                                    </SourceEditorAction>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    )
}
