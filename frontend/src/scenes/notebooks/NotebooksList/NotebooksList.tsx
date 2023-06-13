import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { NotebookListItemType } from '~/types'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { notebooksListLogic } from '../Notebook/notebooksListLogic'
import { useEffect, useMemo, useState } from 'react'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { router } from 'kea-router'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { IconDelete, IconEllipsis } from 'lib/lemon-ui/icons'

export function NotebooksTable(): JSX.Element {
    const { notebooks, notebooksLoading, fuse } = useValues(notebooksListLogic)
    const { loadNotebooks } = useActions(notebooksListLogic)
    const [searchTerm, setSearchTerm] = useState('')

    const filteredNotebooks = useMemo(
        () => (searchTerm ? fuse.search(searchTerm).map(({ item }) => item) : notebooks),
        [searchTerm, notebooks, fuse]
    )

    useEffect(() => {
        loadNotebooks()
    }, [])

    const columns: LemonTableColumns<NotebookListItemType> = [
        {
            title: 'Title',
            dataIndex: 'title',
            width: '100%',
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
                                            notebooksListLogic.actions.deleteNotebook(
                                                notebook.short_id,
                                                notebook?.title
                                            )
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
                    onClick: () => router.actions.push(urls.notebook('template-introduction')),
                    children: 'Get started',
                }}
            >
                <b>Welcome to the preview of Notebooks</b> - a great way to bring Insights, Replays, Feature Flags and
                many more PostHog prodcuts together into one place.
            </LemonBanner>
            <div className="flex justify-between gap-2 flex-wrap">
                <LemonInput
                    type="search"
                    placeholder="Search for notebooks"
                    onChange={setSearchTerm}
                    value={searchTerm}
                />
            </div>
            <LemonTable
                data-attr="dashboards-table"
                pagination={{ pageSize: 100 }}
                dataSource={filteredNotebooks as NotebookListItemType[]}
                rowKey="short_id"
                columns={columns}
                loading={notebooksLoading}
                defaultSorting={{ columnKey: 'title', order: 1 }}
                emptyState={`No notebooks matching your filters!`}
                nouns={['notebook', 'notebooks']}
            />
        </div>
    )
}
