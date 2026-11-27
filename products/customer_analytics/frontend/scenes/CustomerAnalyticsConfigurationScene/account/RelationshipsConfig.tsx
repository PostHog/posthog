import { useActions, useValues } from 'kea'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import {
    Button,
    Empty,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import type { AccountRelationshipDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { RelationshipDefinitionModal } from './RelationshipDefinitionModal'
import { relationshipDefinitionsLogic } from './relationshipDefinitionsLogic'

export function RelationshipsConfig(): JSX.Element {
    const { definitions, definitionsLoading } = useValues(relationshipDefinitionsLogic)
    const { openCreateModal, openEditModal, deleteDefinition } = useActions(relationshipDefinitionsLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const confirmDelete = (definition: AccountRelationshipDefinitionApi): void => {
        LemonDialog.open({
            title: `Delete ${definition.name}?`,
            description: `Deleting ${definition.name} also deletes its entire assignment history on all accounts. This can't be undone.`,
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteDefinition({ id: definition.id }),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-col gap-1">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Relationships
                        </Heading>
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Define the roles your team holds on accounts, like CSM or Onboarding manager.
                        </Text>
                    </div>
                    <Button variant="primary" onClick={openCreateModal} disabledReason={restrictionReason}>
                        New relationship
                    </Button>
                </div>
                {definitionsLoading && definitions.length === 0 ? (
                    <div className="flex flex-col gap-2">
                        <Skeleton className="h-10 w-full" />
                        <Skeleton className="h-10 w-full" />
                    </div>
                ) : (
                    <Table fullWidth className="rounded-md border border-border">
                        <TableHeader>
                            <TableRow>
                                <TableHead>Name</TableHead>
                                <TableHead expand>Description</TableHead>
                                <TableHead />
                            </TableRow>
                        </TableHeader>
                        {definitions.length === 0 ? (
                            <TableEmpty>
                                <Empty>
                                    <EmptyHeader>
                                        <EmptyTitle>No relationships yet. Create one to get started.</EmptyTitle>
                                    </EmptyHeader>
                                </Empty>
                            </TableEmpty>
                        ) : (
                            <TableBody>
                                {definitions.map((definition) => (
                                    <TableRow key={definition.id}>
                                        <TableCell>
                                            <span className="font-semibold">{definition.name}</span>
                                        </TableCell>
                                        <TableCell>
                                            {definition.description ? (
                                                definition.description
                                            ) : (
                                                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                                    —
                                                </Text>
                                            )}
                                        </TableCell>
                                        <TableCell>
                                            <div className="flex justify-end gap-1">
                                                <Button
                                                    size="icon"
                                                    aria-label="Edit"
                                                    tooltip="Edit"
                                                    onClick={() => openEditModal(definition)}
                                                    disabledReason={restrictionReason}
                                                >
                                                    <IconPencil />
                                                </Button>
                                                <Button
                                                    variant="destructive-outline"
                                                    size="icon"
                                                    aria-label="Delete"
                                                    tooltip="Delete"
                                                    onClick={() => confirmDelete(definition)}
                                                    disabledReason={restrictionReason}
                                                >
                                                    <IconTrash />
                                                </Button>
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        )}
                    </Table>
                )}
                <RelationshipDefinitionModal />
            </div>
        )
    }

    const columns: LemonTableColumns<AccountRelationshipDefinitionApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, definition) => <span className="font-semibold">{definition.name}</span>,
        },
        {
            title: 'Description',
            dataIndex: 'description',
            render: (_, definition) =>
                definition.description ? definition.description : <span className="text-secondary">—</span>,
        },
        {
            title: '',
            width: 0,
            render: (_, definition) => (
                <div className="flex gap-1 justify-end">
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Edit"
                        onClick={() => openEditModal(definition)}
                        disabledReason={restrictionReason}
                    />
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        tooltip="Delete"
                        onClick={() => confirmDelete(definition)}
                        disabledReason={restrictionReason}
                    />
                </div>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <div>
                    <h3 className="mb-0">Relationships</h3>
                    <p className="text-secondary mb-0">
                        Define the roles your team holds on accounts, like CSM or Onboarding manager.
                    </p>
                </div>
                <LemonButton type="primary" onClick={openCreateModal} disabledReason={restrictionReason}>
                    New relationship
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={definitions}
                loading={definitionsLoading}
                rowKey="id"
                emptyState="No relationships yet. Create one to get started."
            />
            <RelationshipDefinitionModal />
        </div>
    )
}
