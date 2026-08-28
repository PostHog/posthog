import { useActions, useValues } from 'kea'

import { IconTrash, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    ProfilePicture,
} from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'

import type { AccountRelationshipApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountRelationshipsLogic } from './accountRelationshipsLogic'

const PAGE_SIZE = 10

export function AccountRelationshipsExpansion({ accountId }: { accountId: string }): JSX.Element {
    const {
        relationships,
        relationshipsLoading,
        displayedRelationships,
        definitionFilter,
        definitionFilterOptions,
        relationshipDefinitions,
        assignDefinition,
        assignDefinitionId,
        canDeleteRelationships,
        relationshipSaving,
        relationshipToDelete,
    } = useValues(accountRelationshipsLogic({ accountId }))
    const {
        setDefinitionFilter,
        setAssignDefinitionId,
        assignRelationship,
        endRelationship,
        openDeleteConfirmation,
        closeDeleteConfirmation,
        deleteRelationship,
    } = useActions(accountRelationshipsLogic({ accountId }))

    const columns: LemonTableColumns<AccountRelationshipApi> = [
        {
            title: 'Relationship',
            key: 'definition',
            render: (_, relationship) => <span className="font-semibold">{relationship.definition.name}</span>,
        },
        {
            title: 'Assignee',
            key: 'user',
            render: (_, relationship) =>
                relationship.user ? (
                    <div className="flex items-center gap-2">
                        <ProfilePicture user={{ email: relationship.user.email }} size="sm" />
                        <span className="text-sm">{relationship.user.email}</span>
                    </div>
                ) : (
                    <span className="text-muted italic">Deleted user</span>
                ),
        },
        {
            title: 'Started',
            key: 'started_at',
            width: 140,
            render: (_, relationship) => <TZLabel time={relationship.started_at} />,
        },
        {
            title: 'Ended',
            key: 'ended_at',
            width: 140,
            render: (_, relationship) =>
                relationship.ended_at ? (
                    <TZLabel time={relationship.ended_at} />
                ) : (
                    <LemonTag type="success">Current</LemonTag>
                ),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, relationship) =>
                relationship.ended_at && !canDeleteRelationships ? null : (
                    <div className="flex justify-end gap-1">
                        {!relationship.ended_at && (
                            <LemonButton
                                size="xsmall"
                                icon={<IconX />}
                                tooltip={`End this ${relationship.definition.name} assignment`}
                                disabledReason={relationshipSaving ? 'Saving…' : undefined}
                                onClick={() => endRelationship(relationship)}
                            />
                        )}
                        {canDeleteRelationships && (
                            <LemonButton
                                size="xsmall"
                                status="danger"
                                icon={<IconTrash />}
                                tooltip="Delete assignment"
                                disabledReason={relationshipSaving ? 'Saving…' : undefined}
                                data-attr="account-relationships-delete-button"
                                onClick={() => openDeleteConfirmation(relationship)}
                            />
                        )}
                    </div>
                ),
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <LemonSelect
                    size="small"
                    placeholder="All relationships"
                    allowClear
                    value={definitionFilter}
                    onChange={(value) => setDefinitionFilter(value ?? null)}
                    options={definitionFilterOptions.map((definition) => ({
                        value: definition.id,
                        label: definition.name,
                    }))}
                    data-attr="account-relationships-definition-filter"
                />
                <div className="flex items-center gap-2">
                    <LemonSelect
                        size="small"
                        placeholder="Relationship to assign"
                        allowClear
                        value={assignDefinitionId}
                        onChange={(value) => setAssignDefinitionId(value ?? null)}
                        options={relationshipDefinitions.map((definition) => ({
                            value: definition.id,
                            label: definition.name,
                        }))}
                        data-attr="account-relationships-assign-definition"
                    />
                    <MemberSelect
                        value={null}
                        allowNone={false}
                        onChange={(user) => user && assignDefinition && assignRelationship(assignDefinition, user)}
                    >
                        {() => (
                            <LemonButton
                                type="primary"
                                size="small"
                                loading={relationshipSaving}
                                disabledReason={
                                    !assignDefinition
                                        ? 'Pick a relationship to assign first'
                                        : relationshipSaving
                                          ? 'Saving…'
                                          : undefined
                                }
                                data-attr="account-relationships-assign-button"
                            >
                                Assign
                            </LemonButton>
                        )}
                    </MemberSelect>
                </div>
            </div>
            <LemonTable<AccountRelationshipApi>
                size="small"
                embedded
                dataSource={displayedRelationships}
                rowKey="id"
                loading={relationshipsLoading}
                columns={columns}
                pagination={{ pageSize: PAGE_SIZE, useUrl: false }}
                emptyState={
                    relationships === null ? 'Failed to load relationships.' : 'No assignments on this account yet.'
                }
            />
            <LemonModal
                isOpen={relationshipToDelete !== null}
                onClose={() => !relationshipSaving && closeDeleteConfirmation()}
                title="Delete assignment?"
                footer={
                    <>
                        <LemonButton
                            type="secondary"
                            onClick={closeDeleteConfirmation}
                            disabledReason={relationshipSaving ? 'Deleting…' : undefined}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            status="danger"
                            loading={relationshipSaving}
                            data-attr="account-relationships-delete-confirm-button"
                            onClick={() => {
                                if (relationshipToDelete) {
                                    deleteRelationship(relationshipToDelete)
                                }
                            }}
                        >
                            Delete assignment
                        </LemonButton>
                    </>
                }
            >
                {relationshipToDelete && (
                    <p className="mb-0">
                        This permanently deletes the {relationshipToDelete.definition.name} assignment. This can't be
                        undone.
                    </p>
                )}
            </LemonModal>
        </div>
    )
}
