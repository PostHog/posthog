import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import type { Sorting } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { DashboardTemplateEditor } from 'scenes/dashboard/DashboardTemplateEditor'
import { dashboardTemplateEditorLogic } from 'scenes/dashboard/dashboardTemplateEditorLogic'
import { userLogic } from 'scenes/userLogic'

import { DashboardTemplateType } from '~/types'

const templatesTableLogic = dashboardTemplatesLogic({ scope: 'default' })

const POPULAR_TEMPLATE_TOOLTIP = 'One of our most popular templates'

export const DashboardTemplatesTable = (): JSX.Element | null => {
    const { allTemplates, allTemplatesLoading, templateFilter, templateNameOrdering } = useValues(templatesTableLogic)
    const { setTemplateFilter, setTemplateNameOrdering } = useActions(templatesTableLogic)

    const nameSorting: Sorting | null = useMemo(
        () =>
            !templateNameOrdering
                ? null
                : {
                      columnKey: 'template_name',
                      order: templateNameOrdering === '-template_name' ? -1 : 1,
                  },
        [templateNameOrdering]
    )

    const { openDashboardTemplateEditor, setDashboardTemplateId, deleteDashboardTemplate, updateDashboardTemplate } =
        useActions(dashboardTemplateEditorLogic)

    const { user } = useValues(userLogic)

    const columns: LemonTableColumns<DashboardTemplateType> = [
        {
            key: 'featured',
            width: '2rem',
            align: 'center',
            className: 'align-middle',
            render: (_, record) => (
                <span className="inline-flex min-h-5 w-full items-center justify-center leading-none">
                    {record.scope === 'global' && record.is_featured ? (
                        <Tooltip title={POPULAR_TEMPLATE_TOOLTIP}>
                            <IconThumbsUpFilled className="size-4 text-success" aria-label={POPULAR_TEMPLATE_TOOLTIP} />
                        </Tooltip>
                    ) : null}
                </span>
            ),
        },
        {
            title: 'Name',
            dataIndex: 'template_name',
            sorter: true,
            render: (_, { template_name }) => {
                return <>{template_name}</>
            },
        },
        {
            title: 'Description',
            dataIndex: 'dashboard_description',
            render: (_, { dashboard_description }) => {
                return <>{dashboard_description}</>
            },
        },
        {
            title: 'Type',
            dataIndex: 'team_id',
            render: (_, { scope }) => {
                if (scope === 'global') {
                    return <LemonSnack>Official</LemonSnack>
                }
                return <LemonSnack>Team</LemonSnack>
            },
        },
        {
            width: 0,
            render: (_, { id, scope }: DashboardTemplateType) => {
                if (!user?.is_staff) {
                    return null
                }
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    onClick={() => {
                                        if (id === undefined) {
                                            console.error('Dashboard template id not defined')
                                            return
                                        }
                                        setDashboardTemplateId(id)
                                        openDashboardTemplateEditor()
                                    }}
                                    fullWidth
                                >
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    onClick={() => {
                                        if (id === undefined) {
                                            console.error('Dashboard template id not defined')
                                            return
                                        }
                                        updateDashboardTemplate({
                                            id,
                                            dashboardTemplateUpdates: {
                                                scope: scope === 'global' ? 'team' : 'global',
                                            },
                                        })
                                    }}
                                    fullWidth
                                >
                                    Make visible to {scope === 'global' ? 'this team only' : 'everyone'}
                                </LemonButton>

                                <LemonDivider />
                                <LemonButton
                                    onClick={() => {
                                        if (id === undefined) {
                                            console.error('Dashboard template id not defined')
                                            return
                                        }
                                        LemonDialog.open({
                                            title: 'Delete dashboard template?',
                                            description: 'This action cannot be undone.',
                                            primaryButton: {
                                                status: 'danger',
                                                children: 'Delete',
                                                onClick: () => {
                                                    deleteDashboardTemplate(id)
                                                },
                                            },
                                        })
                                    }}
                                    fullWidth
                                    status="danger"
                                    disabledReason={
                                        scope === 'global'
                                            ? 'Cannot delete global dashboard templates, make them team only first'
                                            : undefined
                                    }
                                >
                                    Delete dashboard
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <>
            <div className="mb-4 max-w-100">
                <LemonInput
                    type="search"
                    placeholder="Search dashboard templates (min. 3 characters)"
                    onChange={setTemplateFilter}
                    value={templateFilter}
                    fullWidth
                    data-attr="dashboard-templates-search"
                />
            </div>
            <LemonTable
                id="dashboard-templates"
                data-attr="dashboards-template-table"
                pagination={{ pageSize: 25 }}
                dataSource={Object.values(allTemplates)}
                columns={columns}
                loading={allTemplatesLoading}
                sorting={nameSorting}
                onSort={(newSorting) => {
                    if (!newSorting) {
                        setTemplateNameOrdering('')
                        return
                    }
                    setTemplateNameOrdering(newSorting.order === 1 ? 'template_name' : '-template_name')
                }}
                useURLForSorting={false}
                emptyState={<>There are no dashboard templates.</>}
                nouns={['template', 'templates']}
            />
            <DashboardTemplateEditor />
        </>
    )
}
