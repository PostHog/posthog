import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonInput, LemonInputSelect, LemonLabel, LemonSkeleton, ProfilePicture } from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Link } from 'lib/lemon-ui/Link'
import { fullName } from 'lib/utils/strings'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'
import { urls } from 'scenes/urls'

import type { AccountNoteApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountsEvents } from '../Accounts/constants'
import { accountNotesLogic } from './accountNotesLogic'

export function AccountNotesTabContent(): JSX.Element {
    const {
        accountNotes,
        accountNotesResponse,
        accountNotesResponseLoading,
        search,
        createdByFilter,
        accountFilter,
        accountOptions,
        accountOptionsResponseLoading,
        pagination,
    } = useValues(accountNotesLogic)
    const { setSearch, setCreatedByFilter, setAccountFilter, setAccountSearch } = useActions(accountNotesLogic)
    const { selectNotebook } = useActions(notebookPanelLogic)

    const hasFilters = !!search || createdByFilter.length > 0 || accountFilter !== null

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
        {
            title: 'Created by',
            key: 'created_by',
            render: function Render(_, note) {
                const user = note.created_by
                if (!user) {
                    return <span className="text-muted">—</span>
                }
                return (
                    <div className="flex items-center gap-2">
                        <ProfilePicture
                            user={{ email: user.email, first_name: user.first_name, last_name: user.last_name }}
                            size="sm"
                        />
                        <span className="whitespace-nowrap">{fullName(user) || user.email}</span>
                    </div>
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
            <div className="flex flex-wrap items-end gap-3">
                <div className="flex flex-col gap-1">
                    <LemonLabel>Search</LemonLabel>
                    <LemonInput
                        type="search"
                        placeholder="Search notes"
                        onChange={setSearch}
                        value={search}
                        size="small"
                        className="min-w-64"
                        data-attr="account-notes-search"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Created by</LemonLabel>
                    <div className="min-w-64">
                        <MemberSelectMultiple
                            idKey="id"
                            value={createdByFilter}
                            onChange={(users) => setCreatedByFilter(users.map((user) => user.id))}
                        />
                    </div>
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Account</LemonLabel>
                    <LemonInputSelect
                        mode="single"
                        className="min-w-64"
                        placeholder="All accounts"
                        value={accountFilter ? [accountFilter.id] : []}
                        options={accountOptions}
                        loading={accountOptionsResponseLoading}
                        disableFiltering
                        singleValueAsSnack
                        onInputChange={setAccountSearch}
                        onChange={(values) => {
                            const id = values[0]
                            if (!id) {
                                setAccountFilter(null)
                                return
                            }
                            const option = accountOptions.find((candidate) => candidate.key === id)
                            setAccountFilter({ id, name: option?.label ?? id })
                        }}
                        data-attr="account-notes-account-filter"
                    />
                </div>
            </div>
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
                        hasFilters
                            ? 'No notes matching your filters'
                            : "No account notes yet. Create notes from an account's Notes tab."
                    }
                    nouns={['note', 'notes']}
                />
            )}
        </div>
    )
}
