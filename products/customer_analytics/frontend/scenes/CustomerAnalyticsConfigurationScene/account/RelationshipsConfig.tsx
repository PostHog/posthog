import { useActions, useValues } from 'kea'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
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
