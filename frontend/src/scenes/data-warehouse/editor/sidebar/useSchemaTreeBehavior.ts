import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { escapePropertyAsHogQLIdentifier } from 'lib/utils/hogql'
import { newInternalTab } from 'lib/utils/newInternalTab'
import {
    MANAGED_TRINO_SCHEMA_SCOPE,
    getDatabaseSchemaQueryScope,
} from 'scenes/data-management/database/databaseTableListLogic'
import { OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { urls } from 'scenes/urls'

import { POSTHOG_WAREHOUSE } from 'products/data_warehouse/frontend/shared/logics/connectionSelectorLogic'
import { expressionModalLogic } from 'products/data_warehouse/frontend/shared/logics/expressionModalLogic'
import { joinsDataLogic } from 'products/data_warehouse/frontend/shared/logics/joinsDataLogic'

import { dataWarehouseViewsLogic } from '../../saved_queries/dataWarehouseViewsLogic'
import { draftsLogic } from '../draftsLogic'
import { queryDatabaseLogic } from './queryDatabaseLogic'
import { SchemaItemAction, getSchemaItemActions } from './schemaItemActions'
import { getColumnInsertText, getQueryDatabaseTreeData } from './schemaTreeData'

export interface SchemaTreeBehavior {
    treeData: TreeDataItem[]
    renameSavedViewEnabled: boolean
    isPreviewableViewItem: (item: TreeDataItem) => boolean
    previewItem: (item: TreeDataItem) => void
    /** What clicking a row does: insert a column, open a draft, a metric or an unsaved query. */
    activateItem: (item: TreeDataItem) => void
    getActionGroups: (item: TreeDataItem) => SchemaItemAction[][] | null
    /** The Sources heading's add button: opens a new source in a new tab. */
    addSource: () => void
}

/**
 * What the SQL editor's schema tree does, shared by the LemonTree sidebar and the quill Tree in the
 * redesigned editor. Only how each tree draws its rows differs.
 */
export function useSchemaTreeBehavior(extraTreeSections?: TreeDataItem[]): SchemaTreeBehavior {
    const { searchText, joinsByFieldName, visibleTreeData, connectionId, featureFlags } = useValues(queryDatabaseLogic)
    const {
        selectSourceTable,
        toggleEditJoinModal,
        setEditingDraft,
        openUnsavedQuery,
        deleteUnsavedQuery,
        openPropertyDefinitionEditor,
        openRenameView,
    } = useActions(queryDatabaseLogic)
    const {
        createDataWarehouseSavedQueryFolder,
        deleteDataWarehouseSavedQueryFolder,
        updateDataWarehouseSavedQueryFolder,
        deleteDataWarehouseSavedQuery,
    } = useActions(dataWarehouseViewsLogic)
    const { deleteJoin } = useActions(joinsDataLogic)
    const { expressionsByFieldName } = useValues(expressionModalLogic)
    const { openNewExpressionModal, openEditExpressionModal, deleteExpression } = useActions(expressionModalLogic)
    const { deleteDraft } = useActions(draftsLogic)
    const {
        openMaterializationModal,
        openAccessControlModal,
        runQuery,
        setActiveTab,
        setQueryInput,
        setSourceQuery,
        insertTextAtCursor,
    } = useActions(sqlEditorLogic)
    const { isEmbeddedMode, sourceQuery } = useValues(sqlEditorLogic)
    useMountedLogic(sqlEditorLogic)

    // Embedded editors mount no modals (SQLEditor gates them on FullScene), so an access control
    // item there opens nothing. Most embedded callers hide the tree entirely, but not all.
    const warehouseAccessControlEnabled =
        !!featureFlags[FEATURE_FLAGS.HOGQL_WAREHOUSE_ACCESS_CONTROL] && !isEmbeddedMode
    const renameSavedViewEnabled = !!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_RENAME_SAVED_VIEW]
    const isManagedTrino = connectionId === MANAGED_TRINO_SCHEMA_SCOPE
    const schemaQueryScope = {
        ...getDatabaseSchemaQueryScope(connectionId && connectionId !== POSTHOG_WAREHOUSE ? connectionId : undefined),
        ...(isManagedTrino ? { sendRawQuery: true } : {}),
    }

    const isPreviewableViewItem = (item: TreeDataItem): boolean =>
        ['view', 'managed-view', 'endpoint'].includes(item.record?.type)

    const previewItem = (item: TreeDataItem): void => {
        if (!isPreviewableViewItem(item)) {
            return
        }

        const table = item.record?.tableName || item.name
        const previewQuery = `SELECT * FROM ${escapePropertyAsHogQLIdentifier(table)} LIMIT 100`

        if (isEmbeddedMode) {
            setActiveTab(OutputTab.Results)
            setSourceQuery({
                ...sourceQuery,
                source: {
                    ...sourceQuery.source,
                    ...schemaQueryScope,
                    query: previewQuery,
                },
            })
            setQueryInput(previewQuery)
            runQuery(previewQuery, true)
            return
        }

        router.actions.push(
            urls.sqlEditor({
                query: previewQuery,
                outputTab: OutputTab.Results,
                ...schemaQueryScope,
            })
        )
    }

    const openMetricEditor = (item: TreeDataItem): void => {
        const url = urls.sqlEditor({ source: 'metric', metricName: item.record?.metric.name })
        if (isEmbeddedMode) {
            newInternalTab(url)
            return
        }
        router.actions.push(url)
    }

    const treeData = useMemo(
        // Filtered here rather than by the caller: the tree swaps in its own filtered data while
        // searching, so an unfiltered section would sit above the results still listing
        // everything. Keeping the search term on this side also means an embedder doesn't have to
        // mount this logic just to read it.
        () => getQueryDatabaseTreeData(visibleTreeData, extraTreeSections, searchText),
        [extraTreeSections, visibleTreeData, searchText]
    )

    return {
        treeData,
        addSource: () => {
            posthog.capture('sql-editor-add-source-clicked', { source_type: null, location: 'sources_header' })
            newInternalTab(urls.dataWarehouseSourceNew())
        },
        renameSavedViewEnabled,
        isPreviewableViewItem,
        previewItem,
        activateItem: (item) => {
            if (item.record?.type === 'show-all-tables') {
                posthog.capture('sql-editor-show-all-tables-clicked')
            }
            if (item.record?.type === 'draft') {
                router.actions.push(urls.sqlEditor({ draftId: item.record.draft.id }))
            }
            // Insert the column at the cursor, preserving the rest of the query the user has typed
            const columnInsertText = getColumnInsertText(item.record)
            if (columnInsertText) {
                insertTextAtCursor(columnInsertText)
            }
            if (item.record?.type === 'unsaved-query') {
                openUnsavedQuery(item.record)
            }
            if (item.record?.type === 'metric') {
                openMetricEditor(item)
            }
        },
        getActionGroups: (item) =>
            getSchemaItemActions(item, {
                isEmbeddedMode,
                isManagedTrino,
                warehouseAccessControlEnabled,
                renameSavedViewEnabled,
                schemaQueryScope,
                joinsByFieldName,
                expressionsByFieldName,
                previewItem,
                openPropertyDefinitionEditor,
                toggleEditJoinModal,
                deleteJoin,
                openEditExpressionModal,
                deleteExpression,
                openNewExpressionModal,
                setEditingDraft,
                deleteDraft,
                selectSourceTable,
                openAccessControlModal,
                openMaterializationModal,
                openRenameView,
                createDataWarehouseSavedQueryFolder,
                updateDataWarehouseSavedQueryFolder,
                deleteDataWarehouseSavedQueryFolder,
                deleteDataWarehouseSavedQuery,
                openUnsavedQuery,
                deleteUnsavedQuery,
            }),
    }
}
