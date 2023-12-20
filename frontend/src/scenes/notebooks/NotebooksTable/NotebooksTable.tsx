import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { MemberSelect } from 'lib/components/MemberSelect'
import { IconDelete, IconEllipsis } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Link } from 'lib/lemon-ui/Link'
import { useEffect } from 'react'
import { ContainsTypeFilters } from 'scenes/notebooks/NotebooksTable/ContainsTypeFilter'
import { DEFAULT_FILTERS, notebooksTableLogic } from 'scenes/notebooks/NotebooksTable/notebooksTableLogic'
import { urls } from 'scenes/urls'

import { notebooksModel } from '~/models/notebooksModel'
import { NotebookListItemType } from '~/types'

import { notebookPanelLogic } from '../NotebookPanel/notebookPanelLogic'

function titleColumn(): LemonTableColumn<NotebookListItemType, 'title'> {
    return {
        title: 'Title',
        dataIndex: 'title',
        width: '100%',
        render: function Render(title, { short_id, is_template }) {
            return (
                <Link
                    data-attr="notebook-title"
                    to={urls.notebook(short_id)}
                    className="font-semibold flex items-center gap-2"
                >
                    {title || 'Untitled'}
                    {is_template && <LemonTag type="highlight">TEMPLATE</LemonTag>}
                </Link>
            )
        },
        sorter: (a, b) => (a.title ?? 'Untitled').localeCompare(b.title ?? 'Untitled'),
    }
}

export function NotebooksTable(): JSX.Element {
    const { notebooksAndTemplates, filters, notebooksResponseLoading, notebookTemplates, sortValue, pagination } =
        useValues(notebooksTableLogic)
    const { loadNotebooks, setFilters, setSortValue } = useActions(notebooksTableLogic)
    const { selectNotebook } = useActions(notebookPanelLogic)

    useEffect(() => {
        loadNotebooks()
    }, [])

    const columns: LemonTableColumns<NotebookListItemType> = [
        titleColumn() as LemonTableColumn<NotebookListItemType, keyof NotebookListItemType | undefined>,

        createdByColumn<NotebookListItemType>() as LemonTableColumn<
            NotebookListItemType,
            keyof NotebookListItemType | undefined
        >,
        atColumn<NotebookListItemType>('created_at', 'Created') as LemonTableColumn<
            NotebookListItemType,
            keyof NotebookListItemType | undefined
        >,
        atColumn<NotebookListItemType>('last_modified_at', 'Last modified') as LemonTableColumn<
            NotebookListItemType,
            keyof NotebookListItemType | undefined
        >,
        {
            render: function Render(_, notebook) {
                return (
                    <LemonMenu
                        items={[
                            {
                                items: [
                                    {
                                        label: 'Delete',
                                        icon: <IconDelete />,
                                        status: 'danger',

                                        onClick: () => {
                                            notebooksModel.actions.deleteNotebook(notebook.short_id, notebook?.title)
                                        },
                                    },
                                ],
                            },
                        ]}
                        actionable
                    >
                        <LemonButton aria-label="more" icon={<IconEllipsis />} status="stealth" size="small" />
                    </LemonMenu>
                )
            },
        },
    ]

    return (
        <div className="space-y-4">
            <LemonBanner
                type="info"
                action={{
                    onClick: () => {
                        selectNotebook(notebookTemplates[0].short_id)
                    },
                    children: 'Get started',
                }}
                dismissKey="notebooks-preview-banner"
            >
                <b>Welcome to Notebooks</b> - a great way to bring Insights, Replays, Feature Flags and many more
                PostHog products together into one place.
            </LemonBanner>
            <div className="flex justify-between gap-2 flex-wrap">
                <LemonInput
                    type="search"
                    placeholder="Search for notebooks"
                    onChange={(s) => {
                        setFilters({ search: s })
                    }}
                    value={filters.search}
                    data-attr={'notebooks-search'}
                />
                <div className="flex items-center gap-4 flex-wrap">
                    <ContainsTypeFilters filters={filters} setFilters={setFilters} />
                    <div className="flex items-center gap-2">
                        <span>Created by:</span>
                        <MemberSelect
                            size="small"
                            type="secondary"
                            value={filters.createdBy}
                            onChange={(user) => setFilters({ createdBy: user?.uuid || DEFAULT_FILTERS.createdBy })}
                        />
                    </div>
                </div>
            </div>
            <LemonTable
                data-attr="notebooks-table"
                pagination={pagination}
                dataSource={notebooksAndTemplates}
                rowKey="short_id"
                columns={columns}
                loading={notebooksResponseLoading}
                defaultSorting={{ columnKey: '-created_at', order: 1 }}
                emptyState={`No notebooks matching your filters!`}
                nouns={['notebook', 'notebooks']}
                sorting={sortValue ? { columnKey: sortValue, order: sortValue.startsWith('-') ? -1 : 1 } : undefined}
                onSort={(newSorting) =>
                    setSortValue(newSorting ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}` : null)
                }
            />
        </div>
    )
}
