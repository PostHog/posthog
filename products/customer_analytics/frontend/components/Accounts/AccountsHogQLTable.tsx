import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton, LemonColorGlyph, LemonSkeleton, LemonTable, ProfilePicture } from '@posthog/lemon-ui'

import type { DataColorToken } from 'lib/colors'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'
import { Link } from 'lib/lemon-ui/Link'
import { membersLogic } from 'scenes/organization/membersLogic'
import { urls } from 'scenes/urls'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableNode } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn, QueryContextColumnComponent } from '~/queries/types'

import type {
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { ACCOUNTS_HOGQL_DATA_NODE_KEY } from '../../constants'
import { formatCustomPropertyValue } from '../../scenes/CustomerAnalyticsConfigurationScene/account/customPropertyTypes'
import { AccountNotebooksExpansion } from './AccountNotebooksExpansion'
import { ACCOUNTS_NAME_COLUMN, LEGACY_ROLE_COLUMNS, accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import { accountsExpansionLogic } from './accountsExpansionLogic'
import { accountsLogic, savingRoleKey } from './accountsLogic'
import { AccountsEvents } from './constants'

// Shape the backend emits for the `name` column — see accounts_query_runner._calculate.
type AccountNameCell = { name: string; external_id: string | null; id: string }

const COLUMN_WIDTHS = {
    name: '240px',
    tag_names: '280px',
    notebook_count: '80px',
    relationship: '220px',
} as const

function getCellAt(record: unknown, names: string[], column: string): unknown {
    if (!Array.isArray(record)) {
        return undefined
    }
    const index = names.indexOf(column)
    return index >= 0 ? record[index] : undefined
}

function useGetCell(): (record: unknown, column: string) => unknown {
    const { visibleColumnNames } = useValues(accountsColumnConfigLogic)
    return (record, column) => getCellAt(record, visibleColumnNames, column)
}

function getNameCell(record: unknown, visibleColumnNames: string[]): AccountNameCell | undefined {
    const value = getCellAt(record, visibleColumnNames, ACCOUNTS_NAME_COLUMN)
    if (!value || typeof value !== 'object') {
        return undefined
    }
    const cell = value as Partial<AccountNameCell>
    return typeof cell.id === 'string' && typeof cell.name === 'string' ? (cell as AccountNameCell) : undefined
}

// Relationship cells arrive as the array of ACTIVE assignee user ids from the
// `accounts.relationships.values` lazy join ([] when nobody holds the relationship).
function parseAssignedUserIds(value: unknown): number[] {
    if (!Array.isArray(value)) {
        return []
    }
    return value.map((id) => (typeof id === 'number' ? id : Number(id))).filter((id) => Number.isFinite(id))
}

function NameCell({ record }: { record: unknown }): JSX.Element {
    const { visibleColumnNames } = useValues(accountsColumnConfigLogic)
    const { isAccountExpanded } = useValues(accountsExpansionLogic)
    const { toggleAccountExpanded } = useActions(accountsExpansionLogic)
    const cell = getNameCell(record, visibleColumnNames)
    const name = cell?.name ?? ''
    const externalId = cell?.external_id ?? ''
    const accountId = cell?.id
    return (
        <div className="flex flex-col min-w-40" data-account-id={accountId}>
            {accountId ? (
                <Link
                    // Plain click opens the account details inline (keeping the list mounted); the href
                    // stays so a modifier-click (cmd/ctrl/shift) opens the account's deep-link page in a new tab/window.
                    to={urls.customerAnalyticsAccount(accountId)}
                    className="font-semibold"
                    onClick={(event) => {
                        if (event.metaKey || event.ctrlKey || event.shiftKey) {
                            return
                        }
                        event.preventDefault()
                        event.stopPropagation()
                        if (!isAccountExpanded(accountId)) {
                            posthog.capture(AccountsEvents.AccountOpened)
                        }
                        toggleAccountExpanded(accountId)
                    }}
                >
                    {name}
                </Link>
            ) : (
                <span className="font-semibold">{name}</span>
            )}
            {externalId ? (
                <CopyToClipboardInline
                    explicitValue={externalId}
                    iconStyle={{ color: 'var(--color-accent)' }}
                    iconSize="xsmall"
                    description="account ID"
                    className="text-xs text-muted"
                >
                    {externalId}
                </CopyToClipboardInline>
            ) : null}
        </div>
    )
}

function TagsCell({ record }: { record: unknown }): JSX.Element {
    const getCell = useGetCell()
    const raw = getCell(record, 'tag_names')
    const tags = Array.isArray(raw) ? (raw.filter((t) => typeof t === 'string') as string[]) : []
    return tags.length > 0 ? <ObjectTags tags={tags} staticOnly /> : <span className="text-muted">—</span>
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
    const { visibleColumnNames } = useValues(accountsColumnConfigLogic)
    const { updateAccountRole } = useActions(accountsLogic)
    const { meFirstMembers } = useValues(membersLogic)
    const getCell = useGetCell()
    const accountId = getNameCell(record, visibleColumnNames)?.id ?? ''
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

function CustomPropertyCell({
    record,
    column,
    definition,
}: {
    record: unknown
    column: string
    definition: CustomPropertyDefinitionApi
}): JSX.Element {
    const getCell = useGetCell()
    const raw = getCell(record, column)
    const value = raw === null || raw === undefined ? '' : String(raw)

    if (!value) {
        return <span className="text-muted">—</span>
    }
    if (definition.display_type === 'date' || definition.display_type === 'datetime') {
        return <TZLabel time={value} showSeconds={definition.display_type === 'datetime'} />
    }
    if (definition.display_type === 'boolean') {
        return value === 'true' || value === '1' ? <IconCheck /> : <IconX className="text-muted" />
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
            data-attr={`accounts-hogql-sort-${column}`}
        >
            {label}
            <SortingIndicator order={order} />
        </span>
    )
}

// Per-column overrides for known visible columns. The `label` becomes the
// header text (rendered inside `SortableColumnHeader`), `width` pins the
// column width, and `render` provides the cell renderer. Any visible column
// not in this map falls back to a sortable header with the raw column name
// and DataTable's default cell rendering.
type KnownColumnTemplate = {
    label?: string
    width?: string
    render?: QueryContextColumnComponent
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
    const { visibleColumnNames, aliasToDefinition, aliasToRelationshipDefinition } =
        useValues(accountsColumnConfigLogic)
    return useMemo(() => {
        const columns: Record<string, QueryContextColumn> = {}
        for (const key of visibleColumnNames) {
            const definition = aliasToDefinition[key]
            if (definition) {
                columns[key] = {
                    renderTitle: () => <SortableColumnHeader column={key} label={definition.name} />,
                    render: ({ record }) => <CustomPropertyCell record={record} column={key} definition={definition} />,
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
                render: template?.render,
            }
        }
        return columns
    }, [visibleColumnNames, aliasToDefinition, aliasToRelationshipDefinition])
}

function useExpandable(): QueryContext<DataTableNode>['expandable'] {
    const { visibleColumnNames } = useValues(accountsColumnConfigLogic)
    const { expandedAccountIds } = useValues(accountsExpansionLogic)
    const { toggleAccountExpanded } = useActions(accountsExpansionLogic)
    return useMemo(
        () => ({
            noIndent: true,
            expandedRowClassName: '[&>td]:overflow-visible!',
            isRowExpanded: ({ result }) => {
                const cell = getNameCell(result, visibleColumnNames)
                return !!cell && expandedAccountIds.includes(cell.id)
            },
            onRowExpand: ({ result }) => {
                const cell = getNameCell(result, visibleColumnNames)
                if (cell) {
                    toggleAccountExpanded(cell.id)
                }
            },
            onRowCollapse: ({ result }) => {
                const cell = getNameCell(result, visibleColumnNames)
                if (cell) {
                    toggleAccountExpanded(cell.id)
                }
            },
            expandedRowRender: ({ result }) => {
                const cell = getNameCell(result, visibleColumnNames)
                return cell ? (
                    <AccountNotebooksExpansion accountId={cell.id} externalId={cell.external_id ?? ''} />
                ) : null
            },
        }),
        [visibleColumnNames, expandedAccountIds, toggleAccountExpanded]
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

function AccountsHogQLSkeleton(): JSX.Element {
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

export function AccountsHogQLTable(): JSX.Element {
    const { hogqlQuery } = useValues(accountsLogic)
    const { responseLoading, response } = useValues(dataNodeLogic)
    const contextColumns = useContextColumns()
    const expandable = useExpandable()
    if (responseLoading && !response) {
        return <AccountsHogQLSkeleton />
    }
    return (
        <div className="@container">
            <DataTable
                uniqueKey="customer-analytics-accounts-hogql"
                query={hogqlQuery}
                setQuery={() => {
                    // Filters are owned by accountsLogic; column/sort changes from the DataTable are ignored on purpose.
                }}
                context={{
                    columns: contextColumns,
                    expandable,
                    dataNodeLogicKey: ACCOUNTS_HOGQL_DATA_NODE_KEY,
                    emptyStateHeading: 'There are no matching accounts for this query',
                    emptyStateDetail: 'Try adjusting the filters or refreshing',
                }}
                readOnly
            />
        </div>
    )
}
