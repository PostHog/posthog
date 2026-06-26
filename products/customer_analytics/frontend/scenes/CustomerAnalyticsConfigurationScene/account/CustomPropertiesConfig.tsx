import { useActions, useValues } from 'kea'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'
import { CustomPropertyModal } from './CustomPropertyModal'
import { labelForDisplayType } from './customPropertyTypes'

export function CustomPropertiesConfig(): JSX.Element {
    const { definitions, definitionsLoading } = useValues(customPropertyDefinitionsLogic)
    const { openCreateModal, openEditModal, deleteDefinition } = useActions(customPropertyDefinitionsLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const confirmDelete = (definition: CustomPropertyDefinitionApi): void => {
        LemonDialog.open({
            title: `Delete ${definition.name}?`,
            description: `Deleting ${definition.name} removes this custom property. This can't be undone.`,
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteDefinition({ id: definition.id }),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const columns: LemonTableColumns<CustomPropertyDefinitionApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, definition) => <span className="font-semibold">{definition.name}</span>,
        },
        {
            title: 'Type',
            render: (_, definition) => labelForDisplayType(definition.display_type),
        },
        {
            title: 'Description',
            dataIndex: 'description',
            render: (_, definition) =>
                definition.description ? definition.description : <span className="text-secondary">—</span>,
        },
        {
            title: 'Last updated',
            render: (_, definition) =>
                definition.updated_at ? (
                    <TZLabel time={definition.updated_at} />
                ) : (
                    <span className="text-secondary">—</span>
                ),
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
                    <h3 className="mb-0">Custom properties</h3>
                    <p className="text-secondary mb-0">Define typed properties to store on your accounts.</p>
                </div>
                <LemonButton type="primary" onClick={openCreateModal} disabledReason={restrictionReason}>
                    New custom property
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={definitions}
                loading={definitionsLoading}
                rowKey="id"
                emptyState="No custom properties yet. Create one to get started."
            />
            <CustomPropertyModal />
        </div>
    )
}
