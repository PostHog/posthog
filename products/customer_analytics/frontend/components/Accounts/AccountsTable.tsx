import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton, LemonColorGlyph, LemonSkeleton, LemonTable, ProfilePicture } from '@posthog/lemon-ui'

import type { DataColorToken } from 'lib/colors'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { percentage } from 'lib/utils/numbers'
import { membersLogic } from 'scenes/organization/membersLogic'
import { urls } from 'scenes/urls'

import { tagsModel } from '~/models/tagsModel'
import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableNode } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn, QueryContextColumnComponent } from '~/queries/types'

import type {
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { ACCOUNTS_TABLE_DATA_NODE_KEY } from '../../constants'
import { formatCustomPropertyValue } from '../../scenes/CustomerAnalyticsConfigurationScene/account/customPropertyTypes'
import { AccountNameCell } from './AccountNameCell'
import { AccountNotebooksExpansion } from './AccountNotebooksExpansion'
import { AccountColumnDisplayConfig, LEGACY_ROLE_COLUMNS, accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import { AccountExpansionTab, accountsExpansionLogic } from './accountsExpansionLogic'
import { accountsLogic, savingRoleKey } from './accountsLogic'
import { accountsTableCell, isAccountsTableRow } from './accountsTableQuery'
import { AccountsEvents } from './constants'

// Shape the name renderer uses from the keyed AccountsTableRow identity fields.
type AccountNameCellData = { name: string; external_id: string | null; id: string; logo_domain: string | null }

const COLUMN_WIDTHS = {
    name: '280px',
    tag_names: '280px',
    notebook_count: '80px',
    relationship: '220px',
} as const

function useGetCell(): (record: unknown, column: string) => unknown {
    const { accountsTableQueryPlan } = useValues(accountsLogic)
    return (record, column) =>
        isAccountsTableRow(record) ? accountsTableCell(record, column, accountsTableQueryPlan) : undefined
}

function getNameCell(record: unknown): AccountNameCellData | undefined {
    if (!isAccountsTableRow(record)) {
        return undefined
    }
    return {
        id: record.id,
        name: record.name,
        external_id: record.externalId ?? null,
        logo_domain: record.logoDomain ?? null,
    }
}

// Relationship cells carry active assignee user ids and use an empty array when unassigned.
function parseAssignedUserIds(value: unknown): number[] {
    if (!Array.isArray(value)) {
        return []
    }
    return value.map((id) => (typeof id === 'number' ? id : Number(id))).filter((id) => Number.isFinite(id))
}

function NameCell({ record }: { record: unknown }): JSX.Element {
    const { isAccountExpanded } = useValues(accountsExpansionLogic)
    const { toggleAccountExpanded } = useActions(accountsExpansionLogic)
    const cell = getNameCell(record)
    const accountId = cell?.id
    return (
        <AccountNameCell
            accountId={accountId}
            name={cell?.name ?? ''}
            externalId={cell?.external_id}
            logoDomain={cell?.logo_domain}
            onClick={(event) => {
                if (!accountId || event.metaKey || event.ctrlKey || event.shiftKey) {
                    return
                }
                event.preventDefault()
                event.stopPropagation()
                if (!isAccountExpanded(accountId)) {
                    posthog.capture(AccountsEvents.AccountOpened)
                }
                toggleAccountExpanded(accountId)
            }}
        />
    )
}

function TagsCell({ record }: { record: unknown }): JSX.Element {
    const { isTagsSaving, tagOverrides } = useValues(accountsLogic)
    const { updateAccountTags, addTagToFilter } = useActions(accountsLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)
    const getCell = useGetCell()
    const raw = getCell(record, 'tag_names')
    const cellTags = Array.isArray(raw) ? (raw.filter((t) => typeof t === 'string') as string[]) : []
    const accountId = getNameCell(record)?.id
    if (!accountId) {
        return cellTags.length > 0 ? <ObjectTags tags={cellTags} staticOnly /> : <span className="text-muted">—</span>
    }
    const tags = tagOverrides[accountId] ?? cellTags
    return (
        <ObjectTags
            tags={tags}
            onChange={(newTags) => updateAccountTags(accountId, newTags)}
            onTagClick={addTagToFilter}
            saving={isTagsSaving(accountId)}
            tagsAvailable={(tagsAvailable || []).filter((tag) => !tags.includes(tag))}
            data-attr="accounts-tags-cell"
        />
    )
}

function NotebookCountCell({ record }: { record: unknown }): JSX.Element {
    const getCell = useGetCell()
    const count = Number(getCell(record, 'notebook_count')) || 0
    return count > 0 ? <span>{count}</span> : <span className="text-muted">—</span>
}

function RelationshipCell({
    record,
    column,
    definition,
}: {
    record: unknown
    column: string
    definition: AccountRelationshipDefinitionApi
}): JSX.Element {
    const { isRoleSaving, relationshipOverrides } = useValues(accountsLogic)
    const { updateAccountRole } = useActions(accountsLogic)
    const { meFirstMembers } = useValues(membersLogic)
    const getCell = useGetCell()
    const accountId = getNameCell(record)?.id ?? ''
    const override = accountId ? relationshipOverrides[savingRoleKey(accountId, column)] : undefined
    const userIds = override ?? parseAssignedUserIds(getCell(record, column))

    if (!definition.is_single_holder) {
        // ponytail: multi-holder relationships are read-only here; manage them on the
        // account's relationships tab. Add inline multi-assign if it's ever needed.
        const users = userIds.map((id) => meFirstMembers.find((member) => member.user.id === id)?.user ?? null)
        return (
            <div data-attr={`accounts-${column}-cell`} className="flex flex-wrap items-center gap-2">
                {users.length === 0 ? (
                    <span className="text-muted">Unassigned</span>
                ) : (
                    users.map((user, index) => (
                        <span key={userIds[index]} className="inline-flex items-center gap-1 text-sm">
                            {user ? <ProfilePicture user={user} size="sm" /> : null}
                            {user?.email ?? 'Unknown user'}
                        </span>
                    ))
                )}
            </div>
        )
    }

    const saving = accountId ? isRoleSaving(accountId, column) : false
    return (
        <div data-attr={`accounts-${column}-cell`}>
            <MemberSelect
                value={userIds[0] ?? null}
                defaultLabel="Unassigned"
                onChange={(user) => accountId && updateAccountRole(accountId, column, user)}
            >
                {(selectedUser) => (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        loading={saving}
                        disabledReason={saving ? 'Saving…' : undefined}
                        icon={selectedUser ? <ProfilePicture user={selectedUser} size="sm" /> : undefined}
                    >
                        {selectedUser ? (
                            <span className="text-sm">{selectedUser.email}</span>
                        ) : userIds.length > 0 ? (
                            <span className="text-sm">Unknown user</span>
                        ) : (
                            <span className="text-muted">Unassigned</span>
                        )}
                    </LemonButton>
                )}
            </MemberSelect>
        </div>
    )
}

// History points arrive in timestamp order from the Postgres runner.
function parseHistoryPoints(raw: unknown): [number, number][] {
    if (!Array.isArray(raw)) {
        return []
    }
    const points: [number, number][] = []
    for (const entry of raw) {
        if (typeof entry !== 'object' || entry === null || !('timestamp' in entry) || !('value' in entry)) {
            continue
        }
        const timestamp = Math.floor(Date.parse(String(entry.timestamp)) / 1000)
        const value = Number(entry.value)
        if (Number.isFinite(timestamp) && Number.isFinite(value)) {
            points.push([timestamp, value])
        }
    }
    return points
}

export interface HistoryDisplay {
    latest: [number, number] | null
    /** The value in effect at the window start: the last write before the cutoff,
     * carried forward, so sparsely-written properties still chart at any window. */
    baseline: [number, number] | null
    chartPoints: [number, number][]
}

export function buildHistoryDisplay(allPoints: [number, number][], windowDays: number, nowMs: number): HistoryDisplay {
    const cutoff = Math.floor(nowMs / 1000) - windowDays * 24 * 60 * 60
    const inWindow = allPoints.filter(([timestamp]) => timestamp >= cutoff)
    const lastBefore = allPoints.filter(([timestamp]) => timestamp < cutoff).at(-1) ?? null
    const carriedForward: [number, number] | null = lastBefore ? [cutoff, lastBefore[1]] : null
    const latest = inWindow.at(-1) ?? lastBefore
    return {
        latest,
        baseline: carriedForward ?? inWindow[0] ?? null,
        chartPoints: carriedForward ? [carriedForward, ...inWindow] : inWindow,
    }
}

function CustomPropertyHistoryCell({
    raw,
    definition,
    display,
}: {
    raw: unknown
    definition: CustomPropertyDefinitionApi
    display: AccountColumnDisplayConfig
}): JSX.Element {
    const { latest, baseline, chartPoints } = buildHistoryDisplay(
        parseHistoryPoints(raw),
        display.window_days,
        dayjs().valueOf()
    )

    if (!latest) {
        return <span className="text-muted">—</span>
    }
    const formatValue = (value: number): string => formatCustomPropertyValue(String(value), definition)
    if (chartPoints.length < 2) {
        return (
            <Tooltip title="Not enough history to chart yet — showing the current value.">
                <span>{formatValue(latest[1])}</span>
            </Tooltip>
        )
    }

    if (display.mode === 'sparkline') {
        // Each sparkline auto-scales to its own range, so the line shows the trend but not the
        // magnitude — every row looks alike without the latest value spelled out next to it.
        return (
            // `min-w-min` lets the cell outgrow w-40 instead of spilling a long value into the next
            // column, and the chart keeps a floor so it degrades rather than vanishing.
            <div className="flex items-center gap-2 w-40 min-w-min">
                <span className="tabular-nums whitespace-nowrap">{formatValue(latest[1])}</span>
                <Sparkline
                    type="line"
                    className="h-8 min-w-8"
                    data={chartPoints.map(([, value]) => value)}
                    labels={chartPoints.map(([timestamp]) => dayjs.unix(timestamp).format('MMM D, YYYY HH:mm'))}
                    renderTooltipValue={formatValue}
                />
            </div>
        )
    }

    const delta = latest[1] - baseline![1]
    const deltaClass = delta > 0 ? 'text-success' : delta < 0 ? 'text-danger' : 'text-muted'
    // Percentage change against the window-start value; a zero baseline has no
    // meaningful ratio, so fall back to the absolute delta.
    const deltaText =
        delta === 0
            ? 'No change'
            : baseline![1] === 0
              ? `${delta > 0 ? '+' : '-'}${formatValue(Math.abs(delta))}`
              : `${delta > 0 ? '+' : '-'}${percentage(Math.abs(delta / baseline![1]), 1)}`
    return (
        <Tooltip
            title={`${formatValue(latest[1])} now, compared to ${formatValue(baseline![1])} ${display.window_days} days ago`}
        >
            <span className="inline-flex items-baseline gap-1.5">
                <span>{formatValue(latest[1])}</span>
                <span className={`text-xs ${deltaClass}`}>{deltaText}</span>
            </span>
        </Tooltip>
    )
}

const CANONICAL_PROPERTY_TAB: Record<string, AccountExpansionTab> = {
    'Last Slack message at': 'conversations',
}

export function getCanonicalPropertyTab(definition: CustomPropertyDefinitionApi): AccountExpansionTab | undefined {
    return definition.is_canonical ? CANONICAL_PROPERTY_TAB[definition.name] : undefined
}

function CanonicalTimestampCell({
    record,
    definition,
    value,
    tab,
}: {
    record: unknown
    definition: CustomPropertyDefinitionApi
    value: string
    tab: AccountExpansionTab
}): JSX.Element {
    const { openAccountTab } = useActions(accountsExpansionLogic)
    const accountId = getNameCell(record)?.id
    const label = <TZLabel time={value} showSeconds={definition.display_type === 'datetime'} />

    if (!accountId) {
        return label
    }
    return (
        <Link
            to={urls.customerAnalyticsAccount(accountId, tab)}
            onClick={(event) => {
                // Modifier-click keeps the href's new-tab behavior, matching the account name cell.
                if (event.metaKey || event.ctrlKey || event.shiftKey) {
                    return
                }
                event.preventDefault()
                event.stopPropagation()
                openAccountTab(accountId, tab)
            }}
        >
            {label}
        </Link>
    )
}

function CustomPropertyCell({
    record,
    column,
    definition,
    display,
}: {
    record: unknown
    column: string
    definition: CustomPropertyDefinitionApi
    display?: AccountColumnDisplayConfig
}): JSX.Element {
    const getCell = useGetCell()
    const raw = getCell(record, column)
    if (display) {
        return <CustomPropertyHistoryCell raw={raw} definition={definition} display={display} />
    }
    const value = raw === null || raw === undefined ? '' : String(raw)

    if (!value) {
        return <span className="text-muted">—</span>
    }
    if (definition.display_type === 'date' || definition.display_type === 'datetime') {
        const tab = getCanonicalPropertyTab(definition)
        if (tab) {
            return <CanonicalTimestampCell record={record} definition={definition} value={value} tab={tab} />
        }
        return <TZLabel time={value} showSeconds={definition.display_type === 'datetime'} />
    }
    if (definition.display_type === 'boolean') {
        return value === 'true' || value === '1' ? <IconCheck /> : <IconX className="text-muted" />
    }
    if (definition.display_type === 'link') {
        return (
            <Link to={value} target="_blank" targetBlankIcon={false}>
                {value}
            </Link>
        )
    }
    if (definition.display_type === 'select') {
        const option = definition.options?.find((candidate) => candidate.label === value)
        return (
            <span className="inline-flex items-center gap-1.5">
                {option && <LemonColorGlyph colorToken={option.color as DataColorToken} size="small" />}
                <span>{value}</span>
            </span>
        )
    }
    return <span>{formatCustomPropertyValue(value, definition)}</span>
}

function SortableColumnHeader({ column, label }: { column: string; label: string }): JSX.Element {
    const { sortOrder } = useValues(accountsLogic)
    const { toggleSort } = useActions(accountsLogic)
    const order = sortOrder?.column === column ? (sortOrder.direction === 'asc' ? 1 : -1) : null
    return (
        <span
            role="button"
            tabIndex={0}
            className="inline-flex items-center cursor-pointer select-none"
            onClick={() => toggleSort(column)}
            onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    toggleSort(column)
                }
            }}
            data-attr={`accounts-table-sort-${column}`}
        >
            {label}
            <SortingIndicator order={order} />
        </span>
    )
}

// Per-column overrides for known visible columns. The `label` becomes the
// header text (rendered inside `SortableColumnHeader`), `width` pins the
// column width, and `render` provides the cell renderer. Any visible column
// not in this map uses a sortable header and the direct keyed-cell renderer.
type KnownColumnTemplate = {
    label?: string
    width?: string
    render?: QueryContextColumnComponent
}

function DefaultAccountCell({ record, column }: { record: unknown; column: string }): JSX.Element {
    const getCell = useGetCell()
    const value = getCell(record, column)
    if (value === null || value === undefined || value === '') {
        return <span className="text-muted">—</span>
    }
    return <span>{String(value)}</span>
}

const KNOWN_COLUMN_TEMPLATES: Record<string, KnownColumnTemplate> = {
    name: {
        label: 'Account',
        width: COLUMN_WIDTHS.name,
        render: ({ record }) => <NameCell record={record} />,
    },
    tag_names: {
        label: 'Tags',
        width: COLUMN_WIDTHS.tag_names,
        render: ({ record }) => <TagsCell record={record} />,
    },
    notebook_count: {
        label: 'Notes',
        width: COLUMN_WIDTHS.notebook_count,
        render: ({ record }) => <NotebookCountCell record={record} />,
    },
}

function useContextColumns(): Record<string, QueryContextColumn> {
    const { visibleColumnNames, aliasToDefinition, aliasToRelationshipDefinition, displayByAlias } =
        useValues(accountsColumnConfigLogic)
    return useMemo(() => {
        const columns: Record<string, QueryContextColumn> = {}
        for (const key of visibleColumnNames) {
            const definition = aliasToDefinition[key]
            if (definition) {
                const display = displayByAlias[key]
                columns[key] = {
                    renderTitle: () => <SortableColumnHeader column={key} label={definition.name} />,
                    render: ({ record }) => (
                        <CustomPropertyCell record={record} column={key} definition={definition} display={display} />
                    ),
                }
                continue
            }
            const relationshipDefinition = aliasToRelationshipDefinition[key]
            if (relationshipDefinition) {
                columns[key] = {
                    renderTitle: () => <SortableColumnHeader column={key} label={relationshipDefinition.name} />,
                    width: COLUMN_WIDTHS.relationship,
                    render: ({ record }) => (
                        <RelationshipCell record={record} column={key} definition={relationshipDefinition} />
                    ),
                }
                continue
            }
            const template = KNOWN_COLUMN_TEMPLATES[key]
            const label = template?.label ?? key
            columns[key] = {
                renderTitle: () => <SortableColumnHeader column={key} label={label} />,
                width: template?.width,
                render: template?.render ?? (({ record }) => <DefaultAccountCell record={record} column={key} />),
            }
        }
        return columns
    }, [visibleColumnNames, aliasToDefinition, aliasToRelationshipDefinition, displayByAlias])
}

function useExpandable(): QueryContext<DataTableNode>['expandable'] {
    const { expandedAccountIds } = useValues(accountsExpansionLogic)
    const { toggleAccountExpanded } = useActions(accountsExpansionLogic)
    return useMemo(
        () => ({
            noIndent: true,
            expandedRowClassName: '[&>td]:overflow-visible!',
            isRowExpanded: ({ result }) => {
                const cell = getNameCell(result)
                return !!cell && expandedAccountIds.includes(cell.id)
            },
            onRowExpand: ({ result }) => {
                const cell = getNameCell(result)
                if (cell) {
                    toggleAccountExpanded(cell.id)
                }
            },
            onRowCollapse: ({ result }) => {
                const cell = getNameCell(result)
                if (cell) {
                    toggleAccountExpanded(cell.id)
                }
            },
            expandedRowRender: ({ result }) => {
                const cell = getNameCell(result)
                return cell ? (
                    <AccountNotebooksExpansion accountId={cell.id} externalId={cell.external_id ?? ''} />
                ) : null
            },
        }),
        [expandedAccountIds, toggleAccountExpanded]
    )
}

const SKELETON_ROW_COUNT = 5

const SKELETON_COLUMNS: LemonTableColumns<{ key: number }> = [
    {
        title: 'Account',
        width: COLUMN_WIDTHS.name,
        render: () => (
            <div className="flex flex-col gap-2 mb-1 min-w-40">
                <LemonSkeleton className="h-4 w-32" />
                <LemonSkeleton className="h-3 w-24" />
            </div>
        ),
    },
    {
        title: 'Tags',
        width: COLUMN_WIDTHS.tag_names,
        render: () => (
            <div className="flex gap-1">
                <LemonSkeleton className="h-5 w-16 rounded-full" />
                <LemonSkeleton className="h-5 w-20 rounded-full" />
            </div>
        ),
    },
    {
        title: 'Notes',
        width: COLUMN_WIDTHS.notebook_count,
        render: () => <LemonSkeleton className="h-4 w-4" />,
    },
    ...Object.values(LEGACY_ROLE_COLUMNS).map((label) => ({
        title: label,
        width: COLUMN_WIDTHS.relationship,
        render: () => (
            <div className="flex items-center gap-2">
                <LemonSkeleton.Circle className="h-5 w-5" />
                <LemonSkeleton className="h-4 w-24" />
            </div>
        ),
    })),
]

function AccountsTableSkeleton(): JSX.Element {
    return (
        <LemonTable
            className="DataTable"
            columns={SKELETON_COLUMNS}
            dataSource={Array.from({ length: SKELETON_ROW_COUNT }, (_, key) => ({ key }))}
            rowKey="key"
            expandable={{
                noIndent: true,
                expandedRowRender: () => null,
                rowExpandable: () => true,
            }}
        />
    )
}

export function AccountsTable(): JSX.Element {
    const { accountsDataTableQuery, accountsQuerySource, sortedRowsTransformer } = useValues(accountsLogic)
    const { responseLoading, response } = useValues(
        dataNodeLogic({
            key: ACCOUNTS_TABLE_DATA_NODE_KEY,
            query: accountsQuerySource ?? accountsDataTableQuery.source,
        } as DataNodeLogicProps)
    )
    const contextColumns = useContextColumns()
    const expandable = useExpandable()
    // A null source means the query is still waiting on the relationship
    // definitions — same skeleton as the initial fetch, not an empty table.
    if ((responseLoading || !accountsQuerySource) && !response) {
        return <AccountsTableSkeleton />
    }
    return (
        <div className="@container">
            <DataTable
                uniqueKey="customer-analytics-accounts-table"
                query={accountsDataTableQuery}
                setQuery={() => {
                    // Filters are owned by accountsLogic; column/sort changes from the DataTable are ignored on purpose.
                }}
                context={{
                    columns: contextColumns,
                    expandable,
                    dataTableRowsTransformer: sortedRowsTransformer,
                    dataNodeLogicKey: ACCOUNTS_TABLE_DATA_NODE_KEY,
                    emptyStateHeading: 'There are no matching accounts for this query',
                    emptyStateDetail: 'Try adjusting the filters or refreshing',
                }}
                readOnly
            />
        </div>
    )
}
