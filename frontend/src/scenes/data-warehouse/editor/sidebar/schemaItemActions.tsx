import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { newInternalTab } from 'lib/utils/newInternalTab'
import type { DataWarehouseAccessControlModalProps } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { urls } from 'scenes/urls'

import type { EnterprisePropertyDefinitionApi } from '~/generated/core/api.schemas'
import { AccessControlLevel, AccessControlResourceType, DataWarehouseSavedQuery, DataWarehouseViewLink } from '~/types'

import { endpointModelUrl } from 'products/data_modeling/frontend/endpointModelName'
import type { DataWarehouseExpressionApi } from 'products/data_warehouse/frontend/generated/api.schemas'
import { buildSelectAllQuery } from 'products/data_warehouse/frontend/utils'

import { isJoined } from './queryDatabaseLogic'
import type { LineageTarget } from './SeeLineageMenuItem'

interface SchemaItemActionBase {
    key: string
    label: string
    dataAttr?: string
}

/**
 * One row of a schema tree item's menu. The sidebar draws these with lib/ui menu parts, and the
 * quill sidebar draws them with quill parts, so the rows and what they do are written once here.
 */
export type SchemaItemAction =
    | (SchemaItemActionBase & {
          kind: 'item'
          onSelect: () => void
          /** Set when an access check fails. `onSelect` already does nothing in that case. */
          disabledReason?: string | null
          destructive?: boolean
          /** The row opens a dialog or an inline editor for more input, so a quill row ends its label with "…". */
          opensFloatingUi?: boolean
      })
    | (SchemaItemActionBase & {
          kind: 'link'
          href: string
          newTab?: boolean
          /** A side effect that runs before the navigation, such as an analytics capture. */
          onSelect?: () => void
      })
    | (SchemaItemActionBase & {
          kind: 'open'
          href: string
          /**
           * True: the row navigates to `href` and the lib/ui menu adds an icon-only "open in new tab"
           * button beside it. False: the row opens `href` in a new tab, because the embedded editor
           * and endpoints must not replace the current scene.
           */
          openInPlace: boolean
          disabledReason?: string | null
      })
    | (SchemaItemActionBase & {
          kind: 'submenu'
          items: SchemaItemAction[]
      })

export interface SchemaItemActionDeps {
    isEmbeddedMode: boolean
    isManagedTrino: boolean
    /** The access control flag is on and the editor is not embedded, because an embedded editor mounts no modals. */
    warehouseAccessControlEnabled: boolean
    renameSavedViewEnabled: boolean
    schemaQueryScope: Record<string, any>
    joinsByFieldName: Record<string, DataWarehouseViewLink>
    expressionsByFieldName: Record<string, DataWarehouseExpressionApi>
    previewItem: (item: TreeDataItem) => void
    openPropertyDefinitionEditor: (propertyDefinition: EnterprisePropertyDefinitionApi) => void
    toggleEditJoinModal: (join: DataWarehouseViewLink) => void
    deleteJoin: (join: DataWarehouseViewLink) => void
    openEditExpressionModal: (expression: DataWarehouseExpressionApi) => void
    deleteExpression: (expression: DataWarehouseExpressionApi) => void
    openNewExpressionModal: (tableName: string) => void
    setEditingDraft: (draftId: string) => void
    deleteDraft: (draftId: string) => void
    selectSourceTable: (tableName: string) => void
    openAccessControlModal: (props: DataWarehouseAccessControlModalProps) => void
    openMaterializationModal: (view?: DataWarehouseSavedQuery) => void
    openRenameView: (view: { id: string; name: string }) => void
    createDataWarehouseSavedQueryFolder: (name: string) => void
    updateDataWarehouseSavedQueryFolder: (folder: { id: string; name: string }) => void
    deleteDataWarehouseSavedQueryFolder: (folderId: string) => void
    deleteDataWarehouseSavedQuery: (viewId: string) => void
    openUnsavedQuery: (record: Record<string, any>) => void
    deleteUnsavedQuery: (record: Record<string, any>) => void
}

export function getSidebarAddJoinSourceTableName(
    recordType: string | undefined,
    itemName: string,
    tableName?: string
): string | null {
    switch (recordType) {
        case 'view':
        case 'managed-view':
            return itemName
        case 'endpoint':
            return tableName ?? null
        default:
            return null
    }
}

const lineageAction = (target: LineageTarget): SchemaItemAction => ({
    kind: 'link',
    key: 'see-lineage',
    label: 'See lineage',
    href: combineUrl(urls.nodeDetail(target.id, 'lineage'), { lookup: target.lookup }).url,
    dataAttr: 'sql-editor-sidebar-see-lineage',
})

const copyNameAction = (key: string, label: string, name: string): SchemaItemAction => ({
    kind: 'item',
    key,
    label,
    onSelect: () => void copyToClipboard(name),
})

const openFolderNameForm = (title: string, initialName: string, onSubmit: (folderName: string) => void): void => {
    LemonDialog.openForm({
        title,
        initialValues: { folderName: initialName },
        content: (
            <LemonField name="folderName">
                <LemonInput placeholder="Enter a folder name" autoFocus />
            </LemonField>
        ),
        errors: {
            folderName: (name) => (!name?.trim() ? 'You must enter a folder name' : undefined),
        },
        onSubmit: ({ folderName }) => onSubmit(folderName.trim()),
    })
}

/**
 * The menu of a schema tree item, as groups of rows in display order, or null when the item has no
 * menu. The lib/ui sidebar draws every group in one menu group, and the quill sidebar puts a
 * separator between groups.
 */
export function getSchemaItemActions(item: TreeDataItem, deps: SchemaItemActionDeps): SchemaItemAction[][] | null {
    const record = item.record
    if (!record || record.type === 'property-field' || record.type === 'sources') {
        return null
    }

    if (record.propertyDefinition) {
        return [
            [
                {
                    kind: 'item',
                    key: 'edit-definition',
                    label: 'Edit definition',
                    opensFloatingUi: true,
                    onSelect: () => deps.openPropertyDefinitionEditor(record.propertyDefinition),
                },
            ],
        ]
    }

    if (record.field && record.table) {
        const fieldKey = `${record.table}.${record.field.name}`
        const join = deps.joinsByFieldName[fieldKey]
        if (join && isJoined(record.field) && join.source_table_name === record.table) {
            return [
                [
                    {
                        kind: 'item',
                        key: 'edit-join',
                        label: 'Edit',
                        opensFloatingUi: true,
                        onSelect: () => deps.toggleEditJoinModal(join),
                    },
                ],
                [{ kind: 'item', key: 'delete-join', label: 'Delete join', onSelect: () => deps.deleteJoin(join) }],
            ]
        }

        const expression = deps.expressionsByFieldName[fieldKey]
        if (expression) {
            return [
                [
                    {
                        kind: 'item',
                        key: 'edit-expression',
                        label: 'Edit expression',
                        opensFloatingUi: true,
                        onSelect: () => deps.openEditExpressionModal(expression),
                    },
                ],
                [
                    {
                        kind: 'item',
                        key: 'delete-expression',
                        label: 'Delete expression',
                        onSelect: () => deps.deleteExpression(expression),
                    },
                ],
            ]
        }
    }

    if (record.type === 'draft') {
        const draft = record.draft
        return [
            [
                {
                    kind: 'item',
                    key: 'rename-draft',
                    label: 'Rename',
                    opensFloatingUi: true,
                    onSelect: () => deps.setEditingDraft(draft.id),
                },
            ],
            [
                {
                    kind: 'item',
                    key: 'delete-draft',
                    label: 'Delete',
                    destructive: true,
                    onSelect: () => deps.deleteDraft(draft.id),
                },
            ],
        ]
    }

    if (record.type === 'metric') {
        const metricName = record.metric.name
        return [
            [
                {
                    kind: 'open',
                    key: 'open-metric',
                    label: 'Open in SQL editor',
                    href: urls.sqlEditor({ source: 'metric', metricName }),
                    openInPlace: !deps.isEmbeddedMode,
                },
                {
                    kind: 'link',
                    key: 'data-catalog',
                    label: 'View in data catalog',
                    href: urls.dataCatalogMetric(metricName),
                },
                ...(!deps.isEmbeddedMode ? [lineageAction({ lookup: 'metric', id: record.metric.id })] : []),
                copyNameAction('copy-metric-name', 'Copy metric name', metricName),
            ],
        ]
    }

    // Project-wide warehouse write actions (Add join, Add expression, Materialization) are gated at
    // the resource level regardless of per-object creator bypass. Per-object actions like Edit view
    // use the view's own user_access_level below.
    const resourceLevelEditorDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.WarehouseObjects,
        AccessControlLevel.Editor
    )
    const addJoinAction = (tableName: string): SchemaItemAction => ({
        kind: 'item',
        key: 'add-join',
        label: 'Add join',
        opensFloatingUi: true,
        disabledReason: resourceLevelEditorDisabledReason,
        onSelect: () => {
            if (resourceLevelEditorDisabledReason) {
                return
            }
            deps.selectSourceTable(tableName)
        },
    })

    if (record.type === 'table') {
        // Per-object access control only exists for actual warehouse tables, not posthog/system tables
        const warehouseTableId =
            deps.warehouseAccessControlEnabled && !deps.isManagedTrino && record.table?.type === 'data_warehouse'
                ? record.table?.id
                : null
        const tableLineageTarget: LineageTarget | null =
            deps.isEmbeddedMode || deps.isManagedTrino
                ? null
                : record.table?.type === 'data_warehouse'
                  ? { lookup: 'warehouse_table', id: record.table.id }
                  : record.table?.type === 'posthog'
                    ? { lookup: 'posthog_table', id: record.table.name }
                    : null

        return [
            [
                {
                    kind: 'item',
                    key: 'query',
                    label: 'Query',
                    onSelect: () =>
                        router.actions.push(
                            urls.sqlEditor({
                                query: buildSelectAllQuery(item.name, null),
                                ...deps.schemaQueryScope,
                            })
                        ),
                },
                ...(tableLineageTarget ? [lineageAction(tableLineageTarget)] : []),
                ...(!deps.isManagedTrino
                    ? [
                          addJoinAction(item.name),
                          {
                              kind: 'item' as const,
                              key: 'add-expression',
                              label: 'Add expression',
                              opensFloatingUi: true,
                              disabledReason: resourceLevelEditorDisabledReason,
                              onSelect: () => {
                                  if (resourceLevelEditorDisabledReason) {
                                      return
                                  }
                                  deps.openNewExpressionModal(item.name)
                              },
                          },
                      ]
                    : []),
                copyNameAction('copy-table-name', 'Copy table name', item.name),
                ...(warehouseTableId
                    ? [
                          {
                              kind: 'item' as const,
                              key: 'access-control',
                              label: 'Access control',
                              opensFloatingUi: true,
                              onSelect: () =>
                                  deps.openAccessControlModal({
                                      resource: AccessControlResourceType.WarehouseTable,
                                      resourceId: warehouseTableId,
                                      name: item.name,
                                  }),
                          },
                      ]
                    : []),
            ],
        ]
    }

    if (record.type === 'views') {
        return [
            [
                {
                    kind: 'item',
                    key: 'new-folder',
                    label: '+ New folder',
                    opensFloatingUi: true,
                    onSelect: () => openFolderNameForm('New folder', '', deps.createDataWarehouseSavedQueryFolder),
                },
                {
                    kind: 'item',
                    key: 'manage-views',
                    label: 'Manage views',
                    onSelect: () => newInternalTab(urls.models()),
                },
                {
                    kind: 'item',
                    key: 'manage-endpoints',
                    label: 'Manage endpoints',
                    onSelect: () => newInternalTab(urls.endpoints()),
                },
            ],
        ]
    }

    if (record.type === 'folder' && record.folderType === 'view-folder') {
        const folder = record.folder
        return [
            [
                {
                    kind: 'item',
                    key: 'rename-folder',
                    label: 'Rename folder',
                    opensFloatingUi: true,
                    onSelect: () =>
                        openFolderNameForm('Rename folder', item.name, (name) =>
                            deps.updateDataWarehouseSavedQueryFolder({ id: folder.id, name })
                        ),
                },
            ],
            [
                {
                    kind: 'item',
                    key: 'delete-folder',
                    label: 'Delete folder',
                    destructive: true,
                    onSelect: () =>
                        LemonDialog.open({
                            title: `Delete folder "${item.name}"?`,
                            description: 'Deleting a folder also deletes every view inside it. This cannot be undone.',
                            primaryButton: {
                                status: 'danger',
                                children: 'Delete folder',
                                onClick: () => deps.deleteDataWarehouseSavedQueryFolder(folder.id),
                            },
                            secondaryButton: {
                                children: 'Cancel',
                            },
                        }),
                },
            ],
        ]
    }

    if (record.type === 'endpoint' || record.type === 'view' || record.type === 'managed-view') {
        const isEndpoint = record.type === 'endpoint'
        const isSavedView = record.type === 'view' && !!record.isSavedQuery
        const addJoinSourceTableName = getSidebarAddJoinSourceTableName(
            record.type,
            item.name,
            isEndpoint ? record.tableName : undefined
        )
        // Edit view is per-object, so creators can edit their own views.
        const editViewAccessDisabledReason = !isEndpoint
            ? getAccessControlDisabledReason(
                  AccessControlResourceType.WarehouseObjects,
                  AccessControlLevel.Editor,
                  record.view?.user_access_level
              )
            : null
        // Only saved views map to the WarehouseView resource; endpoints use the Endpoint resource, managed views have none.
        const warehouseViewId = deps.warehouseAccessControlEnabled && isSavedView ? record.view?.id : null
        const openInPlace = !deps.isEmbeddedMode && !isEndpoint

        const main: SchemaItemAction[] = [
            {
                kind: 'open',
                key: 'edit',
                label: isEndpoint ? 'Edit endpoint' : 'Edit view',
                href: isEndpoint
                    ? endpointModelUrl(record.table?.name ?? item.name)
                    : urls.sqlEditor({ view_id: record.view?.id }),
                openInPlace,
                disabledReason: openInPlace ? editViewAccessDisabledReason : undefined,
            },
            { kind: 'item', key: 'query', label: 'Query', onSelect: () => deps.previewItem(item) },
        ]
        if (
            deps.renameSavedViewEnabled &&
            !deps.isEmbeddedMode &&
            isSavedView &&
            record.view?.managed_viewset_kind === null
        ) {
            main.push({
                kind: 'item',
                key: 'rename-view',
                label: 'Rename view',
                dataAttr: 'data-warehouse-view-rename',
                opensFloatingUi: true,
                disabledReason: editViewAccessDisabledReason,
                onSelect: () => {
                    if (!editViewAccessDisabledReason && record.view) {
                        deps.openRenameView({ id: record.view.id, name: record.view.name })
                    }
                },
            })
        }
        if (!deps.isEmbeddedMode && isSavedView) {
            main.push(lineageAction({ lookup: 'saved_query', id: record.view.id }))
        }
        if (addJoinSourceTableName) {
            main.push(addJoinAction(addJoinSourceTableName))
        }
        if (record.type === 'view') {
            main.push({
                kind: 'item',
                key: 'materialization',
                label: 'Materialization',
                opensFloatingUi: true,
                disabledReason: resourceLevelEditorDisabledReason,
                onSelect: () => {
                    if (resourceLevelEditorDisabledReason) {
                        return
                    }
                    deps.openMaterializationModal(record.view)
                },
            })
        }
        if (!isEndpoint) {
            main.push(copyNameAction('copy-view-name', 'Copy view name', item.name))
        }
        if (warehouseViewId) {
            main.push({
                kind: 'item',
                key: 'access-control',
                label: 'Access control',
                opensFloatingUi: true,
                onSelect: () =>
                    deps.openAccessControlModal({
                        resource: AccessControlResourceType.WarehouseView,
                        resourceId: warehouseViewId,
                        name: item.name,
                    }),
            })
        }

        if (!isSavedView) {
            return [main]
        }
        return [
            main,
            [
                {
                    kind: 'item',
                    key: 'delete-view',
                    label: 'Delete view',
                    destructive: true,
                    disabledReason: editViewAccessDisabledReason,
                    onSelect: () => {
                        if (editViewAccessDisabledReason) {
                            return
                        }
                        LemonDialog.open({
                            title: `Delete view "${item.name}"?`,
                            description: 'Are you sure you want to delete this view? This action cannot be undone.',
                            primaryButton: {
                                status: 'danger',
                                children: 'Delete view',
                                onClick: () => {
                                    if (record.view?.id) {
                                        deps.deleteDataWarehouseSavedQuery(record.view.id)
                                    }
                                },
                            },
                            secondaryButton: {
                                children: 'Cancel',
                            },
                        })
                    },
                },
            ],
        ]
    }

    if (record.type === 'unsaved-query') {
        return [
            [{ kind: 'item', key: 'open', label: 'Open', onSelect: () => deps.openUnsavedQuery(record) }],
            [{ kind: 'item', key: 'discard', label: 'Discard', onSelect: () => deps.deleteUnsavedQuery(record) }],
        ]
    }

    // External source folders get an actions menu: edit the source and add a new one of this type.
    // Only a folder of external data source tables carries `sources`; a schema folder of a
    // direct connection does not.
    if (record.type === 'source-folder' && (record.sources?.length ?? 0) > 0) {
        const sourceType = record.sourceType
        const sources: { id: string; label: string }[] = record.sources
        const editSourceHref = (sourceId: string): string =>
            urls.dataWarehouseSource(`managed-${sourceId}`, 'configuration')
        const openSourceAccessControl = (source: { id: string; label: string }): void =>
            deps.openAccessControlModal({
                resource: AccessControlResourceType.ExternalDataSource,
                resourceId: source.id,
                name: source.label || sourceType || 'Source',
            })

        const actions: SchemaItemAction[] = []
        if (sources.length === 1) {
            actions.push({
                kind: 'link',
                key: 'edit-source',
                label: 'Edit source',
                href: editSourceHref(sources[0].id),
                newTab: true,
            })
        } else {
            actions.push({
                kind: 'submenu',
                key: 'edit-source',
                label: 'Edit source',
                items: sources.map(
                    (source): SchemaItemAction => ({
                        kind: 'link',
                        key: source.id,
                        label: source.label,
                        href: editSourceHref(source.id),
                        newTab: true,
                    })
                ),
            })
        }
        if (deps.warehouseAccessControlEnabled) {
            if (sources.length === 1) {
                actions.push({
                    kind: 'item',
                    key: 'access-control',
                    label: 'Access control',
                    opensFloatingUi: true,
                    onSelect: () => openSourceAccessControl(sources[0]),
                })
            } else {
                actions.push({
                    kind: 'submenu',
                    key: 'access-control',
                    label: 'Access control',
                    items: sources.map(
                        (source): SchemaItemAction => ({
                            kind: 'item',
                            key: source.id,
                            label: source.label,
                            opensFloatingUi: true,
                            onSelect: () => openSourceAccessControl(source),
                        })
                    ),
                })
            }
        }
        actions.push({
            kind: 'link',
            key: 'add-source',
            label: 'Add new source of this type',
            href: urls.dataWarehouseSourceNew(sourceType),
            newTab: true,
            onSelect: () =>
                posthog.capture('sql-editor-add-source-clicked', {
                    source_type: sourceType,
                    location: 'source_type_row',
                }),
        })
        return [actions]
    }

    return null
}
