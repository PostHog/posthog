import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDatabase, IconInfo, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Popover } from 'lib/lemon-ui/Popover'
import { urls } from 'scenes/urls'

import type {
    CustomPropertyDefinitionApi,
    CustomPropertyReferenceApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'
import { CustomPropertyModal } from './CustomPropertyModal'
import { CustomPropertySourceModal } from './CustomPropertySourceModal'
import { labelForDisplayType, type SourceSyncStatusLevel, sourceSyncStatus } from './customPropertyTypes'

const TAG_TYPE_BY_SYNC_LEVEL: Record<SourceSyncStatusLevel, LemonTagType> = {
    synced: 'success',
    error: 'danger',
    disabled: 'muted',
    pending: 'default',
}

export function CustomPropertiesConfig(): JSX.Element {
    const { definitions, definitionsLoading } = useValues(customPropertyDefinitionsLogic)
    const { openCreateModal, openEditModal, openSourceModal, deleteDefinition } =
        useActions(customPropertyDefinitionsLogic)
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
            title: (
                <span className="flex items-center gap-1">
                    References
                    <Tooltip title="Workflows that set this property using an 'Update account property' action. Click the count to open them.">
                        <IconInfo className="text-secondary" />
                    </Tooltip>
                </span>
            ),
            render: (_, definition) => <ReferencesCell references={definition.references} />,
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
            title: 'Sync',
            render: (_, definition) => {
                if (!definition.source) {
                    return <span className="text-secondary">Manual</span>
                }
                const status = sourceSyncStatus(definition.source)
                return (
                    <Tooltip title={status.tooltip}>
                        <span className="flex items-center gap-2">
                            <LemonTag type={TAG_TYPE_BY_SYNC_LEVEL[status.level]}>{status.label}</LemonTag>
                            {status.level === 'synced' && definition.source.last_synced_at && (
                                <TZLabel time={definition.source.last_synced_at} className="text-secondary" />
                            )}
                        </span>
                    </Tooltip>
                )
            },
        },
        {
            title: '',
            width: 0,
            render: (_, definition) => (
                <div className="flex gap-1 justify-end">
                    <LemonButton
                        size="small"
                        icon={<IconDatabase />}
                        tooltip={definition.source ? 'Configure sync' : 'Sync from a view'}
                        active={!!definition.source}
                        onClick={() => openSourceModal(definition)}
                        disabledReason={restrictionReason}
                    />
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
            <CustomPropertySourceModal />
        </div>
    )
}

function ReferencesCell({ references }: { references: readonly CustomPropertyReferenceApi[] }): JSX.Element {
    const [open, setOpen] = useState(false)

    if (!references.length) {
        return <span className="text-secondary">0</span>
    }

    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            overlay={
                <div className="flex flex-col gap-1 p-2 max-w-sm">
                    <span className="text-xs text-secondary">Used in</span>
                    {references.map((reference) => (
                        <Link
                            key={reference.id}
                            to={urls.workflow(reference.id, 'workflow')}
                            target="_blank"
                            targetBlankIcon
                        >
                            {reference.name}
                        </Link>
                    ))}
                </div>
            }
        >
            <Link onClick={() => setOpen((isOpen) => !isOpen)}>{references.length}</Link>
        </Popover>
    )
}
