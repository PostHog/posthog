import { useActions, useValues } from 'kea'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'
import { CustomPropertyModal } from './CustomPropertyModal'
import { type SourceSyncStatusLevel, sourceSyncStatus } from './customPropertyTypes'

const TAG_TYPE_BY_SYNC_LEVEL: Record<SourceSyncStatusLevel, LemonTagType> = {
    synced: 'success',
    error: 'danger',
    disabled: 'muted',
    pending: 'default',
}

// Project-settings view of the warehouse → person property sources: the same definitions managed on
// the Customer analytics accounts page, filtered to person targets and created straight into 'person'.
export function WarehousePersonPropertiesSetting(): JSX.Element {
    const { definitions, definitionsLoading } = useValues(customPropertyDefinitionsLogic)
    const { openCreateModal, openEditModal, deleteDefinition } = useActions(customPropertyDefinitionsLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const personDefinitions = definitions.filter((definition) => definition.target_type === 'person')

    const confirmDelete = (definition: CustomPropertyDefinitionApi): void => {
        LemonDialog.open({
            title: `Delete ${definition.name}?`,
            description: `This stops syncing its warehouse columns onto people. Values already synced stay on the people, but they'll stop updating. This can't be undone.`,
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
            title: 'Distinct ID column',
            render: (_, definition) =>
                definition.source?.key_column ? (
                    <code>{definition.source.key_column}</code>
                ) : (
                    <span className="text-secondary">—</span>
                ),
        },
        {
            title: 'Mapped properties',
            render: (_, definition) => {
                const map = (definition.source?.column_property_map ?? {}) as Record<string, string>
                const entries = Object.entries(map)
                if (!entries.length) {
                    return <span className="text-secondary">—</span>
                }
                return (
                    <div className="flex flex-wrap gap-1">
                        {entries.map(([column, property]) => (
                            <LemonTag key={column} type="option">
                                {column} → {property}
                            </LemonTag>
                        ))}
                    </div>
                )
            },
        },
        {
            title: 'Sync',
            render: (_, definition) => {
                if (!definition.source) {
                    return <span className="text-secondary">—</span>
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
            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={() => openCreateModal('person')}
                    disabledReason={restrictionReason}
                >
                    Add person property
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={personDefinitions}
                loading={definitionsLoading}
                rowKey="id"
                emptyState="No warehouse-backed person properties yet. Add one to sync warehouse columns onto people."
            />
            <CustomPropertyModal />
        </div>
    )
}
