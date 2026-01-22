import { IconEllipsis, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { AccessControlLevel } from '~/types'

import { describeAccessControlLevel, humanizeAccessControlLevel } from './helpers'
import { AccessControlRow, AccessControlsTab } from './types'

function getScopeColumnsForTab(activeTab: AccessControlsTab): any[] {
    switch (activeTab) {
        case 'roles':
            return [
                {
                    title: 'Role',
                    key: 'role',
                    render: function RenderRole(_: any, row: AccessControlRow) {
                        return <span>{row.scopeLabel}</span>
                    },
                },
            ]
        case 'members':
            return [
                {
                    title: 'Member',
                    key: 'member',
                    render: function RenderMember(_: any, row: AccessControlRow) {
                        return <span>{row.scopeLabel}</span>
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
    canEditRow: (row: AccessControlRow) => boolean
    onEdit: (row: AccessControlRow) => void
    onDelete: (row: AccessControlRow) => void
}

export function AccessControlTable(props: AccessControlTableProps): JSX.Element {
    const columns = getColumns(props.activeTab, props.canEditRow, props.onEdit, props.onDelete)

    return (
        <LemonTable
            columns={columns}
            dataSource={props.rows}
            loading={props.loading}
            emptyState="No access control rules match these filters"
            pagination={{ pageSize: 50, hideOnSinglePage: true }}
            onRow={(row) => ({
                className: props.canEditRow(row) ? 'cursor-pointer hover:bg-surface-secondary' : undefined,
                onClick: (event) => {
                    if (!props.canEditRow(row)) {
                        return
                    }

                    if ((event.target as HTMLElement).closest('button, a, [role="button"]')) {
                        return
                    }

                    props.onEdit(row)
                },
            })}
        />
    )
}

function getColumns(
    activeTab: AccessControlsTab,
    canEditRow: (row: AccessControlRow) => boolean,
    onEdit: (row: AccessControlRow) => void,
    onDelete: (row: AccessControlRow) => void
): any[] {
    const scopeColumns = getScopeColumnsForTab(activeTab)

    return [
        ...scopeColumns,
        {
            title: 'Feature',
            key: 'resource',
            render: function RenderResource(_: any, row: AccessControlRow) {
                return <span>{row.resourceLabel}</span>
            },
        },
        {
            title: 'Access',
            key: 'rules',
            render: function RenderRules(_: any, row: AccessControlRow) {
                const level = row.level ?? AccessControlLevel.None
                const label = humanizeAccessControlLevel(row.level)

                return (
                    <div className="flex gap-2 flex-wrap">
                        <Tooltip key={level as string} title={describeAccessControlLevel(row.level, row.resourceKey)}>
                            <LemonTag type="default" size="medium" className="px-2">
                                {label}
                            </LemonTag>
                        </Tooltip>
                    </div>
                )
            },
        },
        {
            title: '',
            key: 'actions',
            width: 0,
            align: 'right' as const,
            render: function RenderActions(_: any, row: AccessControlRow) {
                const canEditThisRow = canEditRow(row)
                const disabledReason = !canEditThisRow ? 'You cannot edit this' : undefined
                const canDelete = row.isException && !(row.scopeType === 'default' && row.resourceKey === 'project')

                return (
                    <LemonDropdown
                        placement="bottom-end"
                        closeOnClickInside={true}
                        overlay={
                            <div className="flex flex-col">
                                <LemonButton
                                    size="small"
                                    fullWidth
                                    icon={<IconPencil />}
                                    disabledReason={disabledReason}
                                    onClick={() => onEdit(row)}
                                >
                                    Edit
                                </LemonButton>
                                {canDelete ? (
                                    <LemonButton
                                        size="small"
                                        fullWidth
                                        status="danger"
                                        icon={<IconTrash />}
                                        onClick={() => onDelete(row)}
                                    >
                                        Delete
                                    </LemonButton>
                                ) : null}
                            </div>
                        }
                    >
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconEllipsis />}
                            disabledReason={disabledReason}
                        />
                    </LemonDropdown>
                )
            },
        },
    ]
}
