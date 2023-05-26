import { useActions, useValues } from 'kea'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { NotebookListItemType } from '~/types'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonInput } from '@posthog/lemon-ui'
import { notebooksListLogic } from '../Notebook/notebooksListLogic'
import { useEffect } from 'react'

export function NotebooksTable(): JSX.Element {
    const { notebooks, notebooksLoading } = useValues(notebooksListLogic)
    const { loadNotebooks } = useActions(notebooksListLogic)
    const { filters } = useValues(dashboardsLogic)
    const { setFilters } = useActions(dashboardsLogic)

    useEffect(() => {
        loadNotebooks()
    }, [])

    const columns: LemonTableColumns<NotebookListItemType> = [
        {
            title: 'Title',
            dataIndex: 'title',
            width: '40%',
            render: function Render(title, { short_id }) {
                return (
                    <Link data-attr="notebook-title" to={urls.notebook(short_id)} className="font-semibold">
                        {title || 'Untitled'}
                    </Link>
                )
            },
            sorter: (a, b) => (a.title ?? 'Untitled').localeCompare(b.title ?? 'Untitled'),
        },
        createdByColumn<NotebookListItemType>() as LemonTableColumn<
            NotebookListItemType,
            keyof NotebookListItemType | undefined
        >,
        createdAtColumn<NotebookListItemType>() as LemonTableColumn<
            NotebookListItemType,
            keyof NotebookListItemType | undefined
        >,
    ]

    return (
        <>
            <div className="flex justify-between gap-2 flex-wrap mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search for notebooks"
                    onChange={(x) => setFilters({ search: x })}
                    value={filters.search}
                />
                {/* <div className="flex items-center gap-4 flex-wrap">
                    <div className="flex items-center gap-2">
                        <LemonButton
                            active={filters.pinned}
                            type="secondary"
                            status="stealth"
                            size="small"
                            onClick={() => setFilters({ pinned: !filters.pinned })}
                            icon={<IconPinOutline />}
                        >
                            Pinned
                        </LemonButton>
                    </div>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            active={filters.shared}
                            type="secondary"
                            status="stealth"
                            size="small"
                            onClick={() => setFilters({ shared: !filters.shared })}
                            icon={<IconShare />}
                        >
                            Shared
                        </LemonButton>
                    </div>
                    <div className="flex items-center gap-2">
                        <span>Created by:</span>
                        <LemonSelect
                            options={[
                                { value: 'All users' as string, label: 'All Users' },
                                ...meFirstMembers.map((x) => ({
                                    value: x.user.uuid,
                                    label: x.user.first_name,
                                })),
                            ]}
                            size="small"
                            value={filters.createdBy}
                            onChange={(v: any): void => {
                                setFilters({ createdBy: v })
                            }}
                            dropdownMatchSelectWidth={false}
                        />
                    </div>
                </div> */}
            </div>
            <LemonTable
                data-attr="dashboards-table"
                pagination={{ pageSize: 100 }}
                dataSource={notebooks as NotebookListItemType[]}
                rowKey="short_id"
                columns={columns}
                loading={notebooksLoading}
                defaultSorting={{ columnKey: 'title', order: 1 }}
                emptyState={`No notebooks matching your filters!`}
                nouns={['notebook', 'notebooks']}
            />
        </>
    )
}
