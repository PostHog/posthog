import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
    Input,
    TreeItemActions,
    TreeItemIcon,
    TreeItemLabel,
    TreeItemMeta,
} from '@posthog/quill'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { PropertyDefinitionFilter } from 'scenes/data-warehouse/editor/sidebar/PropertyDefinitionFilter'
import { queryDatabaseLogic } from 'scenes/data-warehouse/editor/sidebar/queryDatabaseLogic'
import { QuillSchemaItemMenuItems } from 'scenes/data-warehouse/editor/sidebar/QuillSchemaItemMenuItems'
import { getFieldTypeIconComponent } from 'scenes/data-warehouse/editor/sidebar/schemaFieldTypeIcons'
import type { SchemaItemAction } from 'scenes/data-warehouse/editor/sidebar/schemaItemActions'
import { formatTraversalChain } from 'scenes/data-warehouse/editor/sidebar/schemaTreeData'
import { getTableKindLabel } from 'scenes/data-warehouse/editor/sidebar/viewKind'

import { MaterializationStatusIcon } from 'products/data_modeling/frontend/MaterializationStatusIcon'
import { TableCertificationIcon } from 'products/data_warehouse/frontend/shared/components/TableCertificationBadge'

const formatRowCount = (count: number | undefined): string | null =>
    count
        ? new Intl.NumberFormat('en', { notation: 'compact', compactDisplay: 'short' }).format(count).toLowerCase()
        : null

/** One row of the schema tree: what follows the Tree's own chevron, plus the row's actions. */
export function QuillSchemaTreeRow({
    item,
    section,
    hasChildren,
    actionGroups,
    onAddSource,
}: {
    item: TreeDataItem
    section: boolean
    hasChildren: boolean
    actionGroups: SchemaItemAction[][] | null
    onAddSource: () => void
}): JSX.Element {
    const { searchText, expandedItemIds, editingDraftId } = useValues(queryDatabaseLogic)
    const { setPropertyDefinitionSearch, renameDraft, setEditingDraft } = useActions(queryDatabaseLogic)
    const record = item.record
    const isColumn = record?.type === 'column'
    const FieldIcon = isColumn ? getFieldTypeIconComponent(record?.field?.type) : null
    const columnType: string | undefined = isColumn ? record?.field?.type : undefined
    const label = typeof item.displayName === 'string' ? item.displayName : item.name
    const certification =
        record?.type === 'table'
            ? record?.table?.certification
            : record?.type === 'view'
              ? record?.certification
              : undefined
    const meta = isColumn
        ? columnType === 'field_traverser'
            ? (formatTraversalChain(record?.field?.chain) ?? columnType)
            : columnType
        : hasChildren
          ? (formatRowCount(record?.row_count) ?? getTableKindLabel(record))
          : null

    if (record?.type === 'draft' && editingDraftId === record?.id) {
        return (
            <Input
                size="sm"
                autoFocus
                defaultValue={item.name}
                aria-label="Draft name"
                className="h-6"
                onClick={(event) => event.stopPropagation()}
                onKeyDown={(event) => {
                    event.stopPropagation()
                    if (event.key === 'Enter') {
                        const name = event.currentTarget.value.trim()
                        if (name && name !== item.name) {
                            renameDraft(record.id, name)
                        }
                        setEditingDraft('')
                    } else if (event.key === 'Escape') {
                        setEditingDraft('')
                    }
                }}
                onBlur={() => setEditingDraft('')}
            />
        )
    }

    return (
        <>
            {!section ? (
                <TreeItemIcon>
                    {FieldIcon ? (
                        <FieldIcon />
                    ) : record?.type === 'view' && record.isSavedQuery ? (
                        <MaterializationStatusIcon view={record.view} />
                    ) : (
                        <TreeNodeDisplayIcon item={item} expandedItemIds={expandedItemIds} />
                    )}
                </TreeItemIcon>
            ) : null}
            <TreeItemLabel highlight={searchText || undefined} className={isColumn ? 'font-mono' : undefined}>
                {label}
            </TreeItemLabel>
            <TableCertificationIcon certification={certification} />
            {meta ? <TreeItemMeta>{meta}</TreeItemMeta> : null}
            {record?.type === 'property-field' ? (
                <TreeItemActions>
                    <PropertyDefinitionFilter
                        propertyDefinitionKey={record.propertyDefinitionKey}
                        propertyDefinitionSearch={record.propertyDefinitionSearch ?? ''}
                        propertyDefinitionTarget={record.propertyDefinitionTarget}
                        setPropertyDefinitionSearch={setPropertyDefinitionSearch}
                    />
                </TreeItemActions>
            ) : record?.type === 'sources' ? (
                <TreeItemActions>
                    <Button
                        size="icon-xs"
                        aria-label="Add a source"
                        tooltip="Add a source"
                        onClick={onAddSource}
                        data-attr="sql-editor-add-source"
                    >
                        <IconPlus />
                    </Button>
                </TreeItemActions>
            ) : actionGroups ? (
                <TreeItemActions>
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={<Button size="icon-xs" aria-label={`More for ${item.name}`} tooltip="More" />}
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" side="right">
                            <QuillSchemaItemMenuItems groups={actionGroups} type="dropdown" />
                        </DropdownMenuContent>
                    </DropdownMenu>
                </TreeItemActions>
            ) : null}
        </>
    )
}
