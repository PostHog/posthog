import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Link } from 'lib/lemon-ui/Link'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'
import { urls } from 'scenes/urls'

import type { AccountNoteApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountsEvents } from '../Accounts/constants'
import { accountNotesLogic } from './accountNotesLogic'

export function AccountNotesTabContent(): JSX.Element {
    const { accountNotes, accountNotesResponse, accountNotesResponseLoading, search, pagination } =
        useValues(accountNotesLogic)
    const { setSearch } = useActions(accountNotesLogic)
    const { selectNotebook } = useActions(notebookPanelLogic)

    const columns: LemonTableColumns<AccountNoteApi> = [
        {
            title: 'Title',
            dataIndex: 'title',
            width: '100%',
            render: function Render(title, note) {
                // Plain click opens the note in the side panel (keeping the list mounted);
                // the href stays so cmd/ctrl-click opens the full notebook page in a new tab.
                return (
                    <Link
                        data-attr="account-note-title"
                        to={urls.notebook(note.short_id)}
                        className="font-semibold"
                        onClick={(event) => {
                            posthog.capture(AccountsEvents.NotesTabNoteClicked, {
                                notebook_short_id: note.short_id,
                            })
                            event.preventDefault()
                            selectNotebook(note.short_id)
                        }}
                    >
                        {title || 'Untitled'}
                    </Link>
                )
            },
        },
        {
            title: 'Account',
            dataIndex: 'account_name',
            render: function Render(accountName, note) {
                return (
                    <Link
                        data-attr="account-note-account"
                        to={urls.customerAnalyticsAccount(note.account_id)}
                        className="whitespace-nowrap"
                        onClick={() => {
                            posthog.capture(AccountsEvents.NotesTabAccountClicked, { account_id: note.account_id })
                        }}
                    >
                        {accountName}
                    </Link>
                )
            },
        },
        atColumn<AccountNoteApi>('created_at', 'Created') as LemonTableColumn<
            AccountNoteApi,
            keyof AccountNoteApi | undefined
        >,
        atColumn<AccountNoteApi>('last_modified_at', 'Last modified') as LemonTableColumn<
            AccountNoteApi,
            keyof AccountNoteApi | undefined
        >,
    ]

    return (
        <div className="space-y-4">
            <LemonInput
                type="search"
                placeholder="Search notes"
                onChange={setSearch}
                value={search}
                size="small"
                className="min-w-64"
                data-attr="account-notes-search"
            />
            {accountNotesResponse === null ? (
                // Dedicated initial-load state (mirrors AccountOpportunitiesExpansion); the
                // table's own loading overlay covers subsequent search/pagination fetches.
                <LemonSkeleton className="h-64 w-full" />
            ) : (
                <LemonTable
                    data-attr="account-notes-table"
                    dataSource={accountNotes}
                    rowKey="short_id"
                    columns={columns}
                    loading={accountNotesResponseLoading}
                    pagination={pagination}
                    emptyState={
                        search
                            ? 'No notes matching your search'
                            : "No account notes yet. Create notes from an account's Notes tab."
                    }
                    nouns={['note', 'notes']}
                />
            )}
        </div>
    )
}
