import { useActions, useValues } from 'kea'

import { IconPlus, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'

import { RelationshipRow, RelationshipStatusFilter, relationshipsLogic } from '../relationshipsLogic'

const STATUS_FILTER_OPTIONS: { value: RelationshipStatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'pending', label: 'Pending' },
    { value: 'active', label: 'Active' },
    { value: 'rejected', label: 'Rejected' },
]

const STATUS_TAG: Record<RelationshipRow['rowStatus'], { label: string; type: 'warning' | 'success' | 'danger' }> = {
    pending: { label: 'Pending', type: 'warning' },
    active: { label: 'Active', type: 'success' },
    rejected: { label: 'Rejected', type: 'danger' },
}

function tableRef(table: string, key: string): string {
    return key ? `${table}.${key}` : table
}

function TableRefCell({ table, refKey }: { table: string; refKey: string }): JSX.Element {
    const value = tableRef(table, refKey)
    return (
        <Tooltip title={value}>
            <span className="font-mono text-xs truncate inline-block max-w-[280px] align-bottom">{value}</span>
        </Tooltip>
    )
}

export function RelationshipsTab(): JSX.Element {
    const { filteredRows, proposalsLoading, joinsLoading, statusFilter, actionsInFlight, joinsById } =
        useValues(relationshipsLogic)
    const { setStatusFilter, acceptProposal, rejectProposal, loadProposals, loadJoins, deleteJoin } =
        useActions(relationshipsLogic)
    const { toggleNewJoinModal, toggleEditJoinModal } = useActions(viewLinkLogic)

    const confirmReject = (row: RelationshipRow): void => {
        if (!row.proposalId) {
            return
        }
        LemonDialog.openForm({
            title: 'Reject this relationship?',
            description: 'Rejecting is permanent: this table pair will not be proposed again.',
            initialValues: { rejectionReason: '' },
            content: (
                <LemonField name="rejectionReason" label="Reason (optional)">
                    <LemonTextArea placeholder="Why is this join wrong?" />
                </LemonField>
            ),
            onSubmit: ({ rejectionReason }) => rejectProposal(row.proposalId as string, rejectionReason || ''),
        })
    }

    const columns: LemonTableColumns<RelationshipRow> = [
        {
            title: 'Source',
            key: 'source',
            render: (_, row) => <TableRefCell table={row.sourceTableName} refKey={row.sourceTableKey} />,
        },
        {
            title: 'Joins to',
            key: 'joining',
            render: (_, row) => <TableRefCell table={row.joiningTableName} refKey={row.joiningTableKey} />,
        },
        {
            title: (
                <Tooltip title="The field added to the source table to reach the joined rows, for example events.person">
                    <span>Accessor</span>
                </Tooltip>
            ),
            key: 'field',
            render: (_, row) => row.fieldName,
        },
        {
            title: 'Confidence',
            key: 'confidence',
            render: (_, row) => (row.confidence != null ? `${Math.round(row.confidence * 100)}%` : ''),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, row) => (
                <div className="flex items-center gap-1">
                    <LemonTag type={STATUS_TAG[row.rowStatus].type}>{STATUS_TAG[row.rowStatus].label}</LemonTag>
                    {row.viaCatalog && <LemonTag type="completion">Via catalog</LemonTag>}
                </div>
            ),
        },
        {
            title: 'Reviewed by',
            key: 'reviewedBy',
            render: (_, row) => row.reviewedBy || <span className="text-secondary">-</span>,
        },
        {
            key: 'actions',
            width: 0,
            render: (_, row) => {
                const join = row.joinId ? joinsById[row.joinId] : null
                if (row.rowStatus === 'active' && join) {
                    return (
                        <More
                            overlay={
                                <>
                                    <LemonButton fullWidth onClick={() => toggleEditJoinModal(join)}>
                                        Edit
                                    </LemonButton>
                                    <LemonButton status="danger" fullWidth onClick={() => deleteJoin(join)}>
                                        Delete
                                    </LemonButton>
                                </>
                            }
                        />
                    )
                }
                if (row.rowStatus !== 'pending' || !row.proposalId) {
                    return null
                }
                const inFlight = !!actionsInFlight[row.proposalId]
                return (
                    // py-1 offsets the negative vertical margin LemonTable applies to buttons in cells
                    <div className="flex gap-1 py-1">
                        <LemonButton
                            type="primary"
                            size="small"
                            loading={inFlight}
                            onClick={() => acceptProposal(row.proposalId as string)}
                        >
                            Accept
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            disabled={inFlight}
                            onClick={() => confirmReject(row)}
                        >
                            Reject
                        </LemonButton>
                    </div>
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="flex justify-between gap-2 flex-wrap items-center">
                <LemonSegmentedButton
                    value={statusFilter}
                    onChange={setStatusFilter}
                    options={STATUS_FILTER_OPTIONS}
                    size="small"
                />
                <div className="flex gap-2">
                    <LemonButton
                        type="secondary"
                        icon={<IconRefresh />}
                        size="small"
                        loading={proposalsLoading || joinsLoading}
                        onClick={() => {
                            loadProposals()
                            loadJoins()
                        }}
                    >
                        Reload
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        size="small"
                        data-attr="data-catalog-new-join"
                        onClick={() => toggleNewJoinModal()}
                    >
                        New join
                    </LemonButton>
                </div>
            </div>
            <LemonTable
                data-attr="data-catalog-relationships-table"
                dataSource={filteredRows}
                rowKey="key"
                columns={columns}
                loading={proposalsLoading || joinsLoading}
                pagination={{ pageSize: 20 }}
                emptyState="No relationships match your filters."
                nouns={['relationship', 'relationships']}
                expandable={{
                    rowExpandable: (row) => !!row.reasoning || !!row.evidence || !!row.rejectionReason,
                    expandedRowRender: (row) => <RelationshipDetail row={row} />,
                }}
            />
            <ViewLinkModal />
        </div>
    )
}

function RelationshipDetail({ row }: { row: RelationshipRow }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 p-2">
            {row.reasoning && (
                <div>
                    <span className="text-secondary">Reasoning</span>
                    <p className="mb-0">{row.reasoning}</p>
                </div>
            )}
            {row.rejectionReason && (
                <div>
                    <span className="text-secondary">Rejection reason</span>
                    <p className="mb-0">{row.rejectionReason}</p>
                </div>
            )}
            {row.evidence != null && (
                <div>
                    <span className="text-secondary">Evidence</span>
                    <CodeSnippet language={Language.JSON}>{JSON.stringify(row.evidence, null, 2)}</CodeSnippet>
                </div>
            )}
        </div>
    )
}
