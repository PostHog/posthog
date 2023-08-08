import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { NotebookListItemType } from '~/types'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'
import { notebooksListLogic } from '../Notebook/notebooksListLogic'
import { useEffect, useMemo, useState } from 'react'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { IconDelete, IconEllipsis } from 'lib/lemon-ui/icons'
import { notebookPopoverLogic } from '../Notebook/notebookPopoverLogic'

export function NotebooksTable(): JSX.Element {
    const { notebooks, notebooksLoading, fuse, notebookTemplates } = useValues(notebooksListLogic)
    const { loadNotebooks } = useActions(notebooksListLogic)
    const [searchTerm, setSearchTerm] = useState('')

    const { setVisibility, selectNotebook } = useActions(notebookPopoverLogic)

    const filteredNotebooks = useMemo(
        () => (searchTerm ? fuse.search(searchTerm).map(({ item }) => item) : [...notebooks, ...notebookTemplates]),
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
                    onClick: () => {
                        selectNotebook(notebookTemplates[0].short_id)
                        setVisibility('visible')
                    },
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
                defaultSorting={{ columnKey: '-created_at', order: 1 }}
                emptyState={`No notebooks matching your filters!`}
                nouns={['notebook', 'notebooks']}
            />
        </div>
    )
}
