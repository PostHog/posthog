import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { AccountNoteApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountNotesLogic } from './accountNotesLogic'

export function AccountNotesTabContent(): JSX.Element {
    const { accountNotes, accountNotesResponseLoading, search, pagination } = useValues(accountNotesLogic)
    const { setSearch } = useActions(accountNotesLogic)

    const columns: LemonTableColumns<AccountNoteApi> = [
        {
            title: 'Title',
            dataIndex: 'title',
            width: '100%',
            render: function Render(title, note) {
                return (
                    <Link
                        data-attr="account-note-title"
                        to={urls.customerAnalyticsAccount(note.account_id, 'notes')}
                        className="font-semibold"
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
                    <Link data-attr="account-note-account" to={urls.customerAnalyticsAccount(note.account_id)}>
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
                data-attr="account-notes-search"
            />
            <LemonTable
                data-attr="account-notes-table"
                dataSource={accountNotes}
                rowKey="short_id"
                columns={columns}
                loading={accountNotesResponseLoading}
                pagination={pagination}
                emptyState="No account notes yet. Create notes from an account's Notes tab."
                nouns={['note', 'notes']}
            />
        </div>
    )
}
