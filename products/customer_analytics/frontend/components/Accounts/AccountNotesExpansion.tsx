import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTableColumns, Link, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { fullName } from 'lib/utils/strings'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'
import { urls } from 'scenes/urls'

import type { AccountNotebookApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountNotebooksLogic } from './accountNotebooksLogic'
import { AccountsEvents } from './constants'

const PREVIEW_MAX_CHARS = 200

function getPreview(notebook: AccountNotebookApi): string {
    const text = (notebook.text_content ?? '').trim()
    if (!text) {
        return ''
    }
    const collapsed = text.replace(/\s+/g, ' ')
    return collapsed.length > PREVIEW_MAX_CHARS ? `${collapsed.slice(0, PREVIEW_MAX_CHARS).trimEnd()}…` : collapsed
}

export function AccountNotesExpansion({
    accountId,
    embedded = true,
}: {
    accountId: string
    embedded?: boolean
}): JSX.Element {
    const logic = accountNotebooksLogic({ accountId })
    const { notebooks, notebooksResponseLoading, createdNoteLoading, searchTerm, sorting, pagination } =
        useValues(logic)
    const { setSearchTerm, setSorting, createNote } = useActions(logic)
    const { selectNotebook } = useActions(notebookPanelLogic)

    const columns: LemonTableColumns<AccountNotebookApi> = [
        {
            title: 'Note',
            key: 'title',
            render: (_, notebook) => {
                const preview = getPreview(notebook)
                return (
                    <div className="flex flex-col gap-1 py-1 max-w-2xl">
                        <Link
                            to={urls.notebook(notebook.short_id)}
                            className="font-medium"
                            onClick={(event) => {
                                posthog.capture(AccountsEvents.NoteClicked, {
                                    notebook_short_id: notebook.short_id,
                                })
                                event.preventDefault()
                                selectNotebook(notebook.short_id)
                            }}
                        >
                            {notebook.title || 'Untitled note'}
                        </Link>
                        {preview ? (
                            <span className="text-xs text-muted line-clamp-2">{preview}</span>
                        ) : (
                            <span className="text-xs text-muted italic">No content yet</span>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Created by',
            key: 'created_by',
            width: 160,
            sorter: true,
            render: (_, notebook) => {
                const user = notebook.created_by
                if (!user) {
                    return <span className="text-muted italic">Unknown</span>
                }
                const name = fullName(user) || user.email
                return (
                    <div className="flex items-center gap-2">
                        <ProfilePicture
                            user={{ email: user.email, first_name: user.first_name, last_name: user.last_name }}
                            size="sm"
                        />
                        <span className="text-sm">{name}</span>
                    </div>
                )
            },
        },
        {
            title: 'Created at',
            key: 'created_at',
            width: 140,
            sorter: true,
            render: (_, notebook) => <TZLabel time={notebook.created_at} />,
        },
    ]

    return (
        <div className="flex flex-col gap-2" data-attr="account-notes">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search notes by title or content..."
                    value={searchTerm}
                    onChange={setSearchTerm}
                    size="small"
                    className="min-w-64"
                />
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPencil />}
                    onClick={createNote}
                    loading={createdNoteLoading}
                >
                    New note
                </LemonButton>
            </div>
            <LemonTable<AccountNotebookApi>
                size="small"
                embedded={embedded}
                dataSource={notebooks ?? []}
                rowKey="short_id"
                loading={notebooksResponseLoading}
                columns={columns}
                sorting={sorting}
                onSort={setSorting}
                pagination={pagination}
                emptyState={
                    notebooks === null
                        ? 'Failed to load account notes.'
                        : searchTerm
                          ? 'No notes match your search.'
                          : 'No notes linked to this account yet.'
                }
            />
        </div>
    )
}
