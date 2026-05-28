import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonTable, ProfilePicture } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableNode } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn } from '~/queries/types'

import { AccountNotebooksExpansion } from './AccountNotebooksExpansion'
import { AccountsColumnConfigurator } from './AccountsColumnConfigurator'
import {
    ACCOUNTS_HOGQL_DATA_NODE_KEY,
    AccountRoleKey,
    AccountSortableColumn,
    accountsLogic,
} from './accountsLogic'

type AccountAssignment = { id: number; email: string } | null

const ROLE_LABELS: Record<AccountRoleKey, string> = {
    csm: 'CSM',
    account_executive: 'Account executive',
    account_owner: 'Account owner',
}

const COLUMN_WIDTHS = {
    name: '240px',
    tag_names: '280px',
    notebook_count: '80px',
    csm: '220px',
    account_executive: '220px',
    account_owner: '220px',
} as const

// Maps logical column names used by the cell renderers to the actual column
// names in the HogQL response. `id` and `external_id` come back under the
// `context.columns.X` prefix so DataTable's existing hidden-flag path filters
// them out of the visible columns — we still need them in the row tuple for
// the row-expand id and the Account cell's external_id rendering. The pinned
// columns are always present in the SELECT (see ACCOUNTS_HOGQL_PINNED_SELECT
// in accountsLogic.ts).
const COLUMN_KEY_OVERRIDES: Record<string, string> = {
    id: 'context.columns.id',
    external_id: 'context.columns.external_id',
}

function getCellAt(record: unknown, names: string[], column: string): unknown {
    if (!Array.isArray(record)) {
        return undefined
    }
    const index = names.indexOf(COLUMN_KEY_OVERRIDES[column] ?? column)
    return index >= 0 ? record[index] : undefined
}

// Pinned columns prepended to the SELECT in this order — see ACCOUNTS_HOGQL_PINNED_SELECT.
const PINNED_COLUMN_NAMES = ['context.columns.id', 'context.columns.external_id']

function useColumnNames(): string[] {
    const { visibleColumnNames } = useValues(accountsLogic)
    return [...PINNED_COLUMN_NAMES, ...visibleColumnNames]
}

function useGetCell(): (record: unknown, column: string) => unknown {
    const names = useColumnNames()
    return (record, column) => getCellAt(record, names, column)
}

function tupleToAssignment(value: unknown): AccountAssignment {
    if (!Array.isArray(value)) {
        return null
    }
    const [id, email] = value as [unknown, unknown]
    if (id === null || id === undefined || typeof email !== 'string' || !email) {
        return null
    }
    const numericId = typeof id === 'number' ? id : Number(id)
    if (!Number.isFinite(numericId)) {
        return null
    }
    return { id: numericId, email }
}

function NameCell({ record }: { record: unknown }): JSX.Element {
    const getCell = useGetCell()
    const name = String(getCell(record, 'name') ?? '')
    const externalId = getCell(record, 'external_id')
    return (
        <div className="flex flex-col min-w-40">
            <span className="font-medium">{name}</span>
            {typeof externalId === 'string' && externalId ? (
                <CopyToClipboardInline
                    explicitValue={externalId}
                    iconStyle={{ color: 'var(--color-accent)' }}
                    description="account ID"
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

function RoleAssignmentCell({ record, role }: { record: unknown; role: AccountRoleKey }): JSX.Element {
    const { isRoleSaving, accountOverrides } = useValues(accountsLogic)
    const { updateAccountRole } = useActions(accountsLogic)
    const getCell = useGetCell()
    const accountId = String(getCell(record, 'id') ?? '')
    const overrideProperties = accountId ? accountOverrides[accountId]?.properties : undefined
    const overrideRole = overrideProperties != null ? overrideProperties[role] : undefined
    const assignment: AccountAssignment =
        overrideRole === undefined ? tupleToAssignment(getCell(record, role)) : (overrideRole as AccountAssignment)
    const saving = accountId ? isRoleSaving(accountId, role) : false

    return (
        <div data-attr={`accounts-${role}-cell`}>
            <MemberSelect
                value={assignment?.id ?? null}
                defaultLabel="Unassigned"
                onChange={(user) => accountId && updateAccountRole(accountId, role, user)}
            >
                {(selectedUser) => (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        loading={saving}
                        disabledReason={saving ? 'Saving…' : undefined}
                        icon={
                            selectedUser ? (
                                <ProfilePicture user={selectedUser} size="sm" />
                            ) : assignment ? (
                                <ProfilePicture user={{ email: assignment.email }} size="sm" />
                            ) : undefined
                        }
                    >
                        {assignment ? (
                            <span className="text-sm">{assignment.email}</span>
                        ) : (
                            <span className="text-muted">Unassigned</span>
                        )}
                    </LemonButton>
                )}
            </MemberSelect>
        </div>
    )
}

const HIDDEN_COLUMN: QueryContextColumn = { hidden: true }

function SortableColumnHeader({
    column,
    label,
}: {
    column: AccountSortableColumn
    label: string
}): JSX.Element {
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

const CONTEXT: QueryContext<DataTableNode> = {
    columns: {
        id: HIDDEN_COLUMN,
        external_id: HIDDEN_COLUMN,
        name: {
            title: 'Account',
            width: COLUMN_WIDTHS.name,
            render: ({ record }) => <NameCell record={record} />,
        },
        tag_names: {
            title: 'Tags',
            width: COLUMN_WIDTHS.tag_names,
            render: ({ record }) => <TagsCell record={record} />,
        },
        notebook_count: {
            renderTitle: () => <SortableColumnHeader column="notebook_count" label="Notes" />,
            width: COLUMN_WIDTHS.notebook_count,
            render: ({ record }) => <NotebookCountCell record={record} />,
        },
        csm: {
            renderTitle: () => <SortableColumnHeader column="csm" label={ROLE_LABELS.csm} />,
            width: COLUMN_WIDTHS.csm,
            render: ({ record }) => <RoleAssignmentCell record={record} role="csm" />,
        },
        account_executive: {
            renderTitle: () => (
                <SortableColumnHeader column="account_executive" label={ROLE_LABELS.account_executive} />
            ),
            width: COLUMN_WIDTHS.account_executive,
            render: ({ record }) => <RoleAssignmentCell record={record} role="account_executive" />,
        },
        account_owner: {
            title: ROLE_LABELS.account_owner,
            width: COLUMN_WIDTHS.account_owner,
            render: ({ record }) => <RoleAssignmentCell record={record} role="account_owner" />,
        },
    },
    expandable: {
        noIndent: true,
        // id is the first pinned column in ACCOUNTS_HOGQL_PINNED_SELECT, so it's
        // always at position 0 in the row tuple regardless of user column choices.
        expandedRowRender: ({ result }) => {
            const accountId = Array.isArray(result) ? String(result[0] ?? '') : ''
            return accountId ? <AccountNotebooksExpansion accountId={accountId} /> : null
        },
    },
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
    ...(['csm', 'account_executive', 'account_owner'] as const).map((role) => ({
        title: ROLE_LABELS[role],
        width: COLUMN_WIDTHS[role],
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

function AccountsHogQLDataTable({ query }: { query: DataTableNode }): JSX.Element {
    const { responseLoading, response } = useValues(dataNodeLogic)
    if (responseLoading && !response) {
        return <AccountsHogQLSkeleton />
    }
    return (
        <DataTable
            uniqueKey="customer-analytics-accounts-hogql"
            query={query}
            setQuery={() => {
                // Filters are owned by accountsLogic; column/sort changes from the DataTable are ignored on purpose.
            }}
            context={{ ...CONTEXT, dataNodeLogicKey: ACCOUNTS_HOGQL_DATA_NODE_KEY }}
            readOnly
        />
    )
}

export function AccountsHogQLTable(): JSX.Element {
    const { hogqlQuery } = useValues(accountsLogic)

    return (
        <BindLogic
            logic={dataNodeLogic}
            props={{
                key: ACCOUNTS_HOGQL_DATA_NODE_KEY,
                query: hogqlQuery.source,
            }}
        >
            <div className="flex flex-col gap-2">
                <div className="flex justify-end">
                    <AccountsColumnConfigurator />
                </div>
                <AccountsHogQLDataTable query={hogqlQuery} />
            </div>
        </BindLogic>
    )
}
