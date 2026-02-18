import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, ProfilePicture } from '@posthog/lemon-ui'

import { APIScopeObject } from '~/types'

import { SummarizeAccessLevels } from './SummarizeAccessLevels'
import { AccessControlRow, AccessControlsTab } from './types'

function getScopeColumnsForTab(activeTab: AccessControlsTab): LemonTableColumns<AccessControlRow> {
    switch (activeTab) {
        case 'roles':
            return [
                {
                    title: 'Role',
                    key: 'role',
                    render: function RenderRole(_: any, row: AccessControlRow) {
                        return <span>{row.role.name}</span>
                    },
                },
            ]
        case 'members':
            return [
                {
                    title: 'Member',
                    key: 'member',
                    render: function RenderMember(_: any, row: AccessControlRow) {
                        return (
                            <div className="flex items-center gap-3">
                                {row.member && <ProfilePicture user={row.member.user} />}
                                <div className="overflow-hidden">
                                    <p className="font-medium mb-0 truncate">{row.role.name}</p>
                                    {row.member && (
                                        <p className="text-secondary font-light mb-0 truncate text-xs">
                                            {row.member.user.email}
                                        </p>
                                    )}
                                </div>
                            </div>
                        )
                    },
                },
            ]
        case 'defaults':
            return []
    }
}

export interface AccessControlTableProps {
    activeTab: AccessControlsTab
    rows: AccessControlRow[]
    loading: boolean
    canEditAny: boolean
    onEdit: (row: AccessControlRow) => void
}

export function AccessControlTable(props: AccessControlTableProps): JSX.Element {
    const columns = getColumns(props.activeTab, props.canEditAny, props.onEdit)

    return (
        <LemonTable
            columns={columns}
            dataSource={props.rows}
            loading={props.loading}
            emptyState="No access control rules match these filters"
            pagination={{ pageSize: 50, hideOnSinglePage: true }}
            onRow={(row) => {
                return {
                    className: props.canEditAny ? 'cursor-pointer hover:bg-surface-secondary' : undefined,
                    onClick: (event) => {
                        if (!props.canEditAny) {
                            return
                        }

                        if ((event.target as HTMLElement).closest('button, a, [role="button"]')) {
                            return
                        }

                        props.onEdit(row)
                    },
                }
            }}
        />
    )
}

function getColumns(
    activeTab: AccessControlsTab,
    canEditAny: boolean,
    onEdit: (row: AccessControlRow) => void
): LemonTableColumns<AccessControlRow> {
    const scopeColumns = getScopeColumnsForTab(activeTab)

    return [
        ...scopeColumns,
        {
            title: 'Access',
            key: 'resource',
            render: function RenderResource(_: any, row: AccessControlRow) {
                const accessControlByResource = row.levels.reduce(
                    (acc, child) => {
                        acc[child.resourceKey] = { access_level: child.level }
                        return acc
                    },
                    {} as Record<APIScopeObject, { access_level?: string | null }>
                )

                return <SummarizeAccessLevels accessControlByResource={accessControlByResource} />
            },
        },
        {
            title: '',
            key: 'actions',
            width: 0,
            align: 'right' as const,
            render: function RenderActions(_: any, row: AccessControlRow) {
                return (
                    <LemonButton
                        size="small"
                        fullWidth
                        icon={<IconPencil />}
                        disabledReason={!canEditAny ? 'You cannot edit this' : undefined}
                        onClick={() => onEdit(row)}
                    >
                        Edit
                    </LemonButton>
                )
            },
        },
    ]
}
