import { useActions, useValues } from 'kea'

import { IconEllipsis, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Link } from 'lib/lemon-ui/Link'
import { ContainsTypeFilters } from 'scenes/notebooks/NotebooksTable/ContainsTypeFilter'
import { notebooksTableLogic } from 'scenes/notebooks/NotebooksTable/notebooksTableLogic'
import { urls } from 'scenes/urls'

import { notebooksModel } from '~/models/notebooksModel'

import { NotebookListItemType, NotebooksTab } from '../types'

function titleColumn(): LemonTableColumn<NotebookListItemType, 'title'> {
    return {
        title: 'Title',
        dataIndex: 'title',
        width: '100%',
        render: function Render(title, { short_id }) {
            return (
                <Link
                    data-attr="notebook-title"
                    to={urls.notebook(short_id)}
                    className="font-semibold flex items-center gap-2"
                >
                    {title || 'Untitled'}
                </Link>
            )
        },
        sorter: (a, b) => (a.title ?? 'Untitled').localeCompare(b.title ?? 'Untitled'),
    }
}

export function NotebooksTable(): JSX.Element {
    const { notebooks, filters, notebooksResponseLoading, tableSorting, pagination } = useValues(notebooksTableLogic)
    const { loadNotebooks, setFilters, tableSortingChanged, setTab } = useActions(notebooksTableLogic)

    useOnMountEffect(loadNotebooks)

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
                                label: 'Delete',
                                icon: <IconTrash />,
                                status: 'danger',

                                onClick: () => {
                                    notebooksModel.actions.deleteNotebook(notebook.short_id, notebook?.title)
                                },
                            },
                        ]}
                    >
                        <LemonButton aria-label="more" icon={<IconEllipsis />} size="small" />
                    </LemonMenu>
                )
            },
        },
    ]

    return (
        <div className="deprecated-space-y-4">
            <LemonBanner
                type="info"
                action={{
                    onClick: () => {
                        setTab(NotebooksTab.Templates)
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
                    data-attr="notebooks-search"
                />
                <div className="flex items-center gap-2 flex-wrap">
                    <ContainsTypeFilters filters={filters} setFilters={setFilters} />
                    <div className="flex items-center gap-2">
                        <span>Created by:</span>
                        <MemberSelect
                            value={filters.createdBy}
                            onChange={(user) => setFilters({ createdBy: user?.uuid || null })}
                        />
                    </div>
                </div>
            </div>
            <LemonTable
                data-attr="notebooks-table"
                pagination={pagination}
                dataSource={notebooks}
                rowKey="short_id"
                columns={columns}
                loading={notebooksResponseLoading}
                defaultSorting={tableSorting}
                emptyState={
                    <>
                        No notebooks matching your filters. You can also{' '}
                        <Link onClick={() => setTab(NotebooksTab.Templates)}>start from a template</Link>.
                    </>
                }
                nouns={['notebook', 'notebooks']}
                onSort={tableSortingChanged}
            />
        </div>
    )
}
