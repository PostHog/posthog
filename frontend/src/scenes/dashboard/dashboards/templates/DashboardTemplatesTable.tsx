import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconBuilding, IconChevronDown, IconGlobe, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonMenu, LemonTag } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import type { Sorting } from 'lib/lemon-ui/LemonTable'
import { atColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { dashboardTemplatesLogic } from 'scenes/dashboard/dashboards/templates/dashboardTemplatesLogic'
import { dashboardTemplateEditorLogic } from 'scenes/dashboard/dashboardTemplateEditorLogic'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, AccessControlResourceType, DashboardTemplateType } from '~/types'

import { dashboardTemplateModalLogic } from './dashboardTemplateModalLogic'

const templatesTableLogic = dashboardTemplatesLogic({ scope: 'default', templatesTabList: true })

const POPULAR_TEMPLATE_TOOLTIP = 'One of our most popular templates'

/** Global template with no owning team (PostHog built-ins). Staff may still narrow to the current team via API; used here for delete restrictions. */
function isBuiltInOfficialTemplate(record: Pick<DashboardTemplateType, 'scope' | 'team_id'>): boolean {
    return record.scope === 'global' && record.team_id == null
}

function createdBySortKey(record: DashboardTemplateType): string {
    if (record.scope === 'global') {
        return 'PostHog'
    }
    return record.created_by?.first_name || record.created_by?.email || ''
}

/** Counts chart tiles in template JSON; excludes text cards and button tiles (matches export shape in dashboardLogic). */
function countTemplateInsightTiles(tiles: DashboardTemplateType['tiles'] | undefined): number {
    if (!Array.isArray(tiles)) {
        return 0
    }
    let n = 0
    for (const tile of tiles) {
        if (typeof tile !== 'object' || tile === null) {
            continue
        }
        const t = tile as Record<string, unknown>
        if (typeof t.type === 'string' && t.type.toUpperCase() === 'TEXT') {
            continue
        }
        if (t.button_tile != null) {
            continue
        }
        const tileType = typeof t.type === 'string' ? t.type.toUpperCase() : ''
        if (tileType === 'INSIGHT' || (t.query != null && typeof t.query === 'object')) {
            n += 1
        }
    }
    return n
}

export const DashboardTemplatesTable = (): JSX.Element | null => {
    const { allTemplates, allTemplatesLoading, templateFilter, templateNameOrdering, templatesTabVisibility } =
        useValues(templatesTableLogic)
    const { setTemplateFilter, setTemplateNameOrdering, setTemplatesTabVisibility } = useActions(templatesTableLogic)

    const tableSorting: Sorting | null = useMemo(() => {
        if (!templateNameOrdering) {
            return null
        }
        if (templateNameOrdering === 'template_name' || templateNameOrdering === '-template_name') {
            return {
                columnKey: 'template_name',
                order: templateNameOrdering === '-template_name' ? -1 : 1,
            }
        }
        if (templateNameOrdering === 'created_at' || templateNameOrdering === '-created_at') {
            return {
                columnKey: 'created_at',
                order: templateNameOrdering === '-created_at' ? -1 : 1,
            }
        }
        return null
    }, [templateNameOrdering])

    const { deleteDashboardTemplate, updateDashboardTemplate } = useActions(dashboardTemplateEditorLogic)
    const { openEdit: openDashboardTemplateModalEdit } = useActions(dashboardTemplateModalLogic)

    const { user } = useValues(userLogic)
    const customerDashboardTemplateAuthoring = useFeatureFlag('CUSTOMER_DASHBOARD_TEMPLATE_AUTHORING')
    const canCustomerManageTeamTemplates =
        !user?.is_staff &&
        customerDashboardTemplateAuthoring &&
        userHasAccess(AccessControlResourceType.DashboardTemplate, AccessControlLevel.Editor)

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
            className: 'min-w-[400px] align-top',
            render: (_, { dashboard_description }) => (
                <div className="max-w-3xl break-words">{dashboard_description}</div>
            ),
        },
        {
            title: 'Tags',
            key: 'tags',
            className: 'min-w-48',
            render: (_, { tags }) => {
                const sortedTags = tags?.length ? [...tags].sort() : []
                if (sortedTags.length === 0) {
                    return <ObjectTags tags={[]} staticOnly />
                }
                const visibleTags = sortedTags.slice(0, 2)
                const overflowTags = sortedTags.slice(2)
                return (
                    <div className="inline-flex flex-wrap items-center gap-0.5">
                        <ObjectTags tags={visibleTags} staticOnly />
                        {overflowTags.length > 0 ? (
                            <LemonMenu
                                items={overflowTags.map((tag, index) => ({
                                    key: `${tag}-${index}`,
                                    label: tag,
                                }))}
                            >
                                <LemonTag type="primary" className="inline-flex">
                                    <span>+{overflowTags.length} more</span>
                                    <IconChevronDown className="w-4 h-4" />
                                </LemonTag>
                            </LemonMenu>
                        ) : null}
                    </div>
                )
            },
        },
        {
            title: 'Insight count',
            key: 'insight_tile_count',
            align: 'right',
            width: '6rem',
            render: (_, record) => humanFriendlyNumber(countTemplateInsightTiles(record.tiles)),
        },
        {
            title: 'Type',
            dataIndex: 'team_id',
            render: (_, { scope }) => (scope === 'global' ? 'Official' : 'Team'),
        },
        {
            title: 'Created by',
            key: 'created_by',
            render: (_, record) => {
                if (record.scope === 'global') {
                    return (
                        <div className="flex flex-row flex-nowrap items-center gap-1.5">
                            <span aria-hidden className="text-base leading-none">
                                🦔
                            </span>
                            <span>PostHog</span>
                        </div>
                    )
                }
                const { created_by } = record
                return (
                    <div className="flex flex-row flex-nowrap items-center">
                        {created_by ? (
                            <ProfilePicture user={created_by} size="md" showName />
                        ) : (
                            <span className="text-secondary">Unknown</span>
                        )}
                    </div>
                )
            },
            sorter: (a, b) => createdBySortKey(a).localeCompare(createdBySortKey(b)),
        },
        atColumn<DashboardTemplateType>(
            'created_at',
            'Created',
            (record) => record.created_at ?? undefined
        ) as LemonTableColumn<DashboardTemplateType, keyof DashboardTemplateType | undefined>,
        {
            width: 0,
            render: (_, record: DashboardTemplateType) => {
                const { id, scope } = record
                const builtInOfficial = isBuiltInOfficialTemplate(record)

                if (user?.is_staff) {
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
                                            openDashboardTemplateModalEdit(record)
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
                                            deleteDashboardTemplate({
                                                id,
                                                templateName: record.template_name,
                                            })
                                        }}
                                        fullWidth
                                        status="danger"
                                        disabledReason={
                                            scope === 'global'
                                                ? builtInOfficial
                                                    ? 'Built-in official templates cannot be deleted'
                                                    : 'Cannot delete a global template until it is team-only'
                                                : undefined
                                        }
                                    >
                                        Delete dashboard
                                    </LemonButton>
                                </>
                            }
                        />
                    )
                }

                if (canCustomerManageTeamTemplates && scope === 'team') {
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
                                            openDashboardTemplateModalEdit(record)
                                        }}
                                        fullWidth
                                    >
                                        Edit
                                    </LemonButton>
                                    <LemonDivider />
                                    <LemonButton
                                        onClick={() => {
                                            if (id === undefined) {
                                                console.error('Dashboard template id not defined')
                                                return
                                            }
                                            deleteDashboardTemplate({
                                                id,
                                                templateName: record.template_name,
                                            })
                                        }}
                                        fullWidth
                                        status="danger"
                                    >
                                        Delete
                                    </LemonButton>
                                </>
                            }
                        />
                    )
                }

                return null
            },
        },
    ]

    return (
        <>
            <div className="flex justify-between gap-2 flex-wrap mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search dashboard templates (min. 3 characters)"
                    onChange={setTemplateFilter}
                    value={templateFilter}
                    data-attr="dashboard-templates-search"
                />
                <div className="flex items-center gap-2 flex-wrap">
                    <span>Filter to:</span>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            active={templatesTabVisibility === 'official'}
                            type="secondary"
                            size="small"
                            icon={<IconGlobe />}
                            onClick={() =>
                                setTemplatesTabVisibility(templatesTabVisibility === 'official' ? 'all' : 'official')
                            }
                            data-attr="dashboard-templates-filter-official"
                        >
                            Official
                        </LemonButton>
                        <LemonButton
                            active={templatesTabVisibility === 'project'}
                            type="secondary"
                            size="small"
                            icon={<IconBuilding />}
                            onClick={() =>
                                setTemplatesTabVisibility(templatesTabVisibility === 'project' ? 'all' : 'project')
                            }
                            data-attr="dashboard-templates-filter-team"
                        >
                            Team
                        </LemonButton>
                    </div>
                </div>
            </div>
            <LemonTable
                id="dashboard-templates"
                data-attr="dashboards-template-table"
                pagination={{ pageSize: 25 }}
                dataSource={Object.values(allTemplates)}
                columns={columns}
                loading={allTemplatesLoading}
                sorting={tableSorting}
                onSort={(newSorting) => {
                    if (!newSorting) {
                        setTemplateNameOrdering('')
                        return
                    }
                    const ascending = newSorting.order === 1
                    if (newSorting.columnKey === 'template_name') {
                        setTemplateNameOrdering(ascending ? 'template_name' : '-template_name')
                    } else if (newSorting.columnKey === 'created_at') {
                        setTemplateNameOrdering(ascending ? 'created_at' : '-created_at')
                    }
                }}
                useURLForSorting={false}
                emptyState={<>There are no dashboard templates.</>}
                nouns={['template', 'templates']}
            />
        </>
    )
}
