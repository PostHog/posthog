import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconInfo, IconLogomark, IconPencil, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSegmentedButton,
    LemonTable,
    LemonTableColumns,
    Tooltip,
} from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Popover } from 'lib/lemon-ui/Popover'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type {
    CustomPropertyDefinitionApi,
    CustomPropertyReferenceApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'
import { CustomPropertyModal } from './CustomPropertyModal'
import { CustomPropertySyncRuns } from './CustomPropertySyncRuns'
import { labelForDisplayType, type SourceSyncStatusLevel, sourceSyncStatus } from './customPropertyTypes'

const TAG_TYPE_BY_SYNC_LEVEL: Record<SourceSyncStatusLevel, LemonTagType> = {
    synced: 'success',
    error: 'danger',
    disabled: 'muted',
    pending: 'default',
}

export function CustomPropertiesConfig(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        filteredDefinitions,
        definitionsLoading,
        searchTerm,
        targetTypeFilter,
        runsBySourceId,
        runsCountBySourceId,
        runsOffsetBySourceId,
        runsSearchBySourceId,
        runsLoadingBySourceId,
        runsLoadFailedBySourceId,
    } = useValues(customPropertyDefinitionsLogic)
    const {
        openCreateModal,
        openEditModal,
        deleteDefinition,
        setSearchTerm,
        setTargetTypeFilter,
        setRunsSearch,
        loadRuns,
    } = useActions(customPropertyDefinitionsLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const accountSyncHistoryEnabled = !!featureFlags[FEATURE_FLAGS.WAREHOUSE_ACCOUNT_PROPERTIES_S3_SYNC]

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
            render: (_, definition) => (
                <span className="flex items-center gap-1 font-semibold">
                    {definition.is_canonical && (
                        <Tooltip title="PostHog sets this property automatically">
                            <IconLogomark className="text-lg shrink-0" />
                        </Tooltip>
                    )}
                    {definition.name}
                </span>
            ),
        },
        {
            title: 'Attach to',
            render: (_, definition) =>
                definition.target_type === 'person' ? (
                    <LemonTag type="completion">Person</LemonTag>
                ) : definition.target_type === 'group' ? (
                    <LemonTag type="caution">Group</LemonTag>
                ) : (
                    <LemonTag type="default">Account</LemonTag>
                ),
        },
        {
            title: 'Type',
            // display_type only shapes how an account property renders; a person property is a raw
            // $set value, so there's nothing meaningful to show for it.
            render: (_, definition) =>
                definition.target_type === 'person' ? (
                    <span className="text-secondary">—</span>
                ) : (
                    labelForDisplayType(definition.display_type)
                ),
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
            title: accountSyncHistoryEnabled ? (
                <span className="flex items-center gap-1">
                    Sync
                    <Tooltip title="Expand a warehouse-backed account property to see staging, retries, and account updates.">
                        <IconInfo className="text-secondary" />
                    </Tooltip>
                </span>
            ) : (
                'Sync'
            ),
            render: (_, definition) => {
                if (definition.is_canonical) {
                    return <span className="text-secondary">Auto</span>
                }
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
            render: (_, definition) => {
                const canonicalReason = definition.is_canonical
                    ? "PostHog sets this property automatically, so it can't be edited or deleted."
                    : undefined
                return (
                    <div className="flex gap-1 justify-end">
                        <LemonButton
                            size="small"
                            icon={<IconPencil />}
                            tooltip="Edit"
                            onClick={() => openEditModal(definition)}
                            disabledReason={canonicalReason ?? restrictionReason}
                        />
                        <LemonButton
                            size="small"
                            status="danger"
                            icon={<IconTrash />}
                            tooltip="Delete"
                            onClick={() => confirmDelete(definition)}
                            disabledReason={canonicalReason ?? restrictionReason}
                        />
                    </div>
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <div>
                    <h3 className="mb-0">Custom properties</h3>
                    <p className="text-secondary mb-0">Define typed properties to store on your accounts.</p>
                </div>
                <LemonButton type="primary" onClick={() => openCreateModal()} disabledReason={restrictionReason}>
                    New custom property
                </LemonButton>
            </div>
            <div className="flex items-center gap-2">
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search custom properties"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    className="max-w-80"
                />
                <LemonSegmentedButton
                    size="small"
                    value={targetTypeFilter}
                    onChange={setTargetTypeFilter}
                    options={[
                        { value: 'all', label: 'All' },
                        { value: 'account', label: 'Accounts' },
                        { value: 'person', label: 'Persons' },
                        { value: 'group', label: 'Groups' },
                    ]}
                />
            </div>
            <LemonTable
                columns={columns}
                dataSource={filteredDefinitions}
                loading={definitionsLoading}
                rowKey="id"
                pagination={{ pageSize: 20, hideOnSinglePage: true }}
                expandable={{
                    rowExpandable: (definition) =>
                        accountSyncHistoryEnabled &&
                        definition.target_type === 'account' &&
                        !!definition.source?.saved_query,
                    onRowExpand: (definition) => definition.source && loadRuns({ sourceId: definition.source.id }),
                    noIndent: true,
                    expandedRowRender: (definition) =>
                        definition.source ? (
                            <CustomPropertySyncRuns
                                runs={runsBySourceId[definition.source.id] ?? []}
                                loading={runsLoadingBySourceId[definition.source.id] ?? false}
                                loadFailed={runsLoadFailedBySourceId[definition.source.id] ?? false}
                                targetType="account"
                                searchTerm={runsSearchBySourceId[definition.source.id] ?? ''}
                                entryCount={runsCountBySourceId[definition.source.id] ?? 0}
                                currentPage={Math.floor((runsOffsetBySourceId[definition.source.id] ?? 0) / 20) + 1}
                                onSearch={(searchTerm) => {
                                    if (definition.source) {
                                        setRunsSearch({ sourceId: definition.source.id, searchTerm })
                                    }
                                }}
                                onForward={() => {
                                    if (definition.source) {
                                        loadRuns({
                                            sourceId: definition.source.id,
                                            offset: (runsOffsetBySourceId[definition.source.id] ?? 0) + 20,
                                        })
                                    }
                                }}
                                onBackward={() => {
                                    if (definition.source) {
                                        loadRuns({
                                            sourceId: definition.source.id,
                                            offset: Math.max((runsOffsetBySourceId[definition.source.id] ?? 0) - 20, 0),
                                        })
                                    }
                                }}
                                syncsUrl={
                                    definition.source.saved_query
                                        ? urls.sqlEditor({ view_id: definition.source.saved_query })
                                        : null
                                }
                                onReload={() =>
                                    definition.source &&
                                    loadRuns({
                                        sourceId: definition.source.id,
                                        offset: runsOffsetBySourceId[definition.source.id] ?? 0,
                                    })
                                }
                            />
                        ) : null,
                }}
                emptyState={
                    searchTerm || targetTypeFilter !== 'all'
                        ? 'No custom properties match your filters.'
                        : 'No custom properties yet. Create one to get started.'
                }
            />
            <CustomPropertyModal />
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
