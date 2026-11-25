import { Fragment, useState } from 'react'

import {
    IconChevronDown,
    IconChevronRight,
    IconInfo,
    IconPencil,
    IconPlus,
    IconRefresh,
    IconTrash,
} from '@posthog/icons'
import {
    Badge,
    Button,
    Empty,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Spinner,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { type SourceSyncStatusLevel } from './customPropertyTypes'
import {
    bindsAView,
    LABELS_BY_TARGET,
    rowActionState,
    sourceRunsUrl,
    syncStatusSummary,
} from './warehouseProfileProperties'

const BADGE_VARIANT_BY_SYNC_LEVEL: Record<SourceSyncStatusLevel, 'success' | 'destructive' | 'default'> = {
    synced: 'success',
    error: 'destructive',
    disabled: 'default',
    pending: 'default',
}

const COLUMN_COUNT = 8

function HeadWithHelp({ label, help }: { label: string; help: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            {label}
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={<Button size="icon-xs" aria-label={`About ${label.toLowerCase()}`} />}
                >
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent className="max-w-80">{help}</TooltipContent>
            </Tooltip>
        </span>
    )
}

function EmptyValue(): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<span className="m-0" />}>
            —
        </Text>
    )
}

export interface QuillWarehouseProfilePropertiesTableProps {
    targetType: 'person' | 'group'
    definitions: CustomPropertyDefinitionApi[]
    loading: boolean
    triggeringSourceIds: string[]
    restrictionReason: string | null
    deleteRestrictionReason: string | null
    renderSyncRuns: (definition: CustomPropertyDefinitionApi) => JSX.Element | null
    onExpand: (definition: CustomPropertyDefinitionApi) => void
    onCreate: () => void
    onEdit: (definition: CustomPropertyDefinitionApi) => void
    onDelete: (definition: CustomPropertyDefinitionApi) => void
    onSync: (sourceId: string) => void
    onBackfill: (sourceId: string) => void
}

export function QuillWarehouseProfilePropertiesTable({
    targetType,
    definitions,
    loading,
    triggeringSourceIds,
    restrictionReason,
    deleteRestrictionReason,
    renderSyncRuns,
    onExpand,
    onCreate,
    onEdit,
    onDelete,
    onSync,
    onBackfill,
}: QuillWarehouseProfilePropertiesTableProps): JSX.Element {
    const [expandedIds, setExpandedIds] = useState<string[]>([])

    const labels = LABELS_BY_TARGET[targetType]

    const toggleExpanded = (definition: CustomPropertyDefinitionApi): void => {
        if (expandedIds.includes(definition.id)) {
            setExpandedIds(expandedIds.filter((id) => id !== definition.id))
            return
        }

        setExpandedIds([...expandedIds, definition.id])
        onExpand(definition)
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-end">
                <Button
                    variant="primary"
                    onClick={onCreate}
                    data-attr="add-warehouse-profile-property"
                    disabledReason={restrictionReason}
                >
                    <IconPlus />
                    Add {labels.entity} property
                </Button>
            </div>
            {loading ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                </div>
            ) : (
                <Table fullWidth className="rounded-md border border-border">
                    <TableHeader>
                        <TableRow>
                            <TableHead />
                            <TableHead>Name</TableHead>
                            <TableHead>
                                <HeadWithHelp
                                    label="Reads"
                                    help="The warehouse table or materialized view this property reads its values from."
                                />
                            </TableHead>
                            <TableHead>
                                <HeadWithHelp
                                    label={labels.keyColumn}
                                    help={`The warehouse column holding each row's ${targetType === 'person' ? 'distinct ID' : 'group key'}. It's how a row is matched to ${labels.entityPlural} — rows with no match are skipped.`}
                                />
                            </TableHead>
                            <TableHead expand>
                                <HeadWithHelp
                                    label="Mapped properties"
                                    help={`Which warehouse column is written to which ${labels.entity} property.`}
                                />
                            </TableHead>
                            <TableHead>
                                <HeadWithHelp
                                    label="Sync"
                                    help="State of the most recent run. Expand the row to see the full history."
                                />
                            </TableHead>
                            <TableHead>
                                <HeadWithHelp
                                    label="Next sync"
                                    help="When the table's or view's next sync is due. Approximate — it drifts if the schedule was paused."
                                />
                            </TableHead>
                            <TableHead />
                        </TableRow>
                    </TableHeader>
                    {definitions.length === 0 ? (
                        <TableEmpty>
                            <Empty>
                                <EmptyHeader>
                                    <EmptyTitle>
                                        {`No warehouse-backed ${labels.entity} properties yet. Add one to sync warehouse columns onto ${labels.entityPlural}.`}
                                    </EmptyTitle>
                                </EmptyHeader>
                            </Empty>
                        </TableEmpty>
                    ) : (
                        <TableBody>
                            {definitions.map((definition) => {
                                const source = definition.source
                                const readsName = source?.saved_query_name ?? source?.table_name
                                const readsUrl = source ? sourceRunsUrl(source) : null
                                const mappedProperties = Object.entries(
                                    (source?.column_property_map ?? {}) as Record<string, string>
                                )
                                const syncSummary = source ? syncStatusSummary(source, labels) : null
                                const actionState = rowActionState(definition, triggeringSourceIds, restrictionReason)
                                const isExpanded = expandedIds.includes(definition.id)

                                return (
                                    <Fragment key={definition.id}>
                                        <TableRow>
                                            <TableCell>
                                                {source && (
                                                    <Button
                                                        size="icon-sm"
                                                        aria-label={
                                                            isExpanded ? 'Hide sync history' : 'Show sync history'
                                                        }
                                                        aria-expanded={isExpanded}
                                                        onClick={() => toggleExpanded(definition)}
                                                    >
                                                        {isExpanded ? <IconChevronDown /> : <IconChevronRight />}
                                                    </Button>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                <span className="font-semibold">{definition.name}</span>
                                            </TableCell>
                                            <TableCell>
                                                {source && readsName ? (
                                                    <span className="flex items-center gap-2">
                                                        {readsUrl ? (
                                                            <Button
                                                                variant="link-foreground"
                                                                size="sm"
                                                                nativeButton={false}
                                                                render={<LinkPrimitive to={readsUrl} />}
                                                            >
                                                                {readsName}
                                                            </Button>
                                                        ) : (
                                                            <span>{readsName}</span>
                                                        )}
                                                        <Badge>{bindsAView(source) ? 'View' : 'Table'}</Badge>
                                                    </span>
                                                ) : (
                                                    <EmptyValue />
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                {source?.key_column ? <code>{source.key_column}</code> : <EmptyValue />}
                                            </TableCell>
                                            <TableCell>
                                                {mappedProperties.length ? (
                                                    <div className="flex flex-wrap gap-1">
                                                        {mappedProperties.map(([column, property]) => (
                                                            <Badge key={column}>
                                                                {column} → {property}
                                                            </Badge>
                                                        ))}
                                                    </div>
                                                ) : (
                                                    <EmptyValue />
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                {!source || !syncSummary ? (
                                                    <EmptyValue />
                                                ) : source.latest_run?.status === 'running' ? (
                                                    <Tooltip>
                                                        <TooltipTrigger render={<Badge variant="info" />}>
                                                            <Spinner />
                                                            Syncing
                                                        </TooltipTrigger>
                                                        <TooltipContent>
                                                            A sync or backfill is running for this table right now.
                                                        </TooltipContent>
                                                    </Tooltip>
                                                ) : (
                                                    <span className="flex items-center gap-2">
                                                        {syncSummary.tooltipTitle ? (
                                                            <Tooltip>
                                                                <TooltipTrigger
                                                                    render={
                                                                        <Badge
                                                                            variant={
                                                                                BADGE_VARIANT_BY_SYNC_LEVEL[
                                                                                    syncSummary.status.level
                                                                                ]
                                                                            }
                                                                        />
                                                                    }
                                                                >
                                                                    {syncSummary.status.label}
                                                                </TooltipTrigger>
                                                                <TooltipContent className="max-w-80">
                                                                    {syncSummary.tooltipTitle}
                                                                </TooltipContent>
                                                            </Tooltip>
                                                        ) : (
                                                            <Badge
                                                                variant={
                                                                    BADGE_VARIANT_BY_SYNC_LEVEL[
                                                                        syncSummary.status.level
                                                                    ]
                                                                }
                                                            >
                                                                {syncSummary.status.label}
                                                            </Badge>
                                                        )}
                                                        {syncSummary.status.level === 'synced' &&
                                                            source.last_synced_at && (
                                                                <Text
                                                                    size="xs"
                                                                    variant="muted"
                                                                    render={<span className="m-0" />}
                                                                >
                                                                    <TZLabel time={source.last_synced_at} />
                                                                </Text>
                                                            )}
                                                    </span>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                {source?.next_sync_at ? (
                                                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                                        <TZLabel time={source.next_sync_at} />
                                                    </Text>
                                                ) : (
                                                    <EmptyValue />
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                <div className="flex justify-end gap-1">
                                                    <Button
                                                        size="icon"
                                                        aria-label="Sync now"
                                                        tooltip="Sync now — re-runs the warehouse sync for this table"
                                                        data-attr="sync-warehouse-profile-property"
                                                        onClick={() => source && onSync(source.id)}
                                                        loading={actionState.triggering || actionState.running}
                                                        disabledReason={actionState.disabledReason}
                                                    >
                                                        <IconRefresh />
                                                    </Button>
                                                    <Button
                                                        tooltip="Backfill — reads the whole table to fill in historical rows"
                                                        data-attr="backfill-warehouse-profile-property"
                                                        onClick={() => source && onBackfill(source.id)}
                                                        loading={actionState.triggering || actionState.running}
                                                        disabledReason={actionState.disabledReason}
                                                    >
                                                        Backfill
                                                    </Button>
                                                    <Button
                                                        size="icon"
                                                        aria-label="Edit"
                                                        tooltip="Edit"
                                                        data-attr="edit-warehouse-profile-property"
                                                        onClick={() => onEdit(definition)}
                                                        disabledReason={restrictionReason}
                                                    >
                                                        <IconPencil />
                                                    </Button>
                                                    <Button
                                                        variant="destructive-outline"
                                                        size="icon"
                                                        aria-label="Delete"
                                                        tooltip="Delete"
                                                        data-attr="delete-warehouse-profile-property"
                                                        onClick={() => onDelete(definition)}
                                                        disabledReason={deleteRestrictionReason}
                                                    >
                                                        <IconTrash />
                                                    </Button>
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                        {isExpanded && source && (
                                            <TableRow>
                                                <TableCell colSpan={COLUMN_COUNT}>
                                                    {renderSyncRuns(definition)}
                                                </TableCell>
                                            </TableRow>
                                        )}
                                    </Fragment>
                                )
                            })}
                        </TableBody>
                    )}
                </Table>
            )}
        </div>
    )
}
