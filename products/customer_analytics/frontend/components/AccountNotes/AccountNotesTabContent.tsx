import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconChevronDown, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput, LemonSkeleton, ProfilePicture } from '@posthog/lemon-ui'

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
        createdByCurrentUser,
        accountFilter,
        pagination,
    } = useValues(accountNotesLogic)
    const { setSearch, setCreatedByFilter, setCreatedByCurrentUser, reportFilterChange } = useActions(accountNotesLogic)
    const { selectNotebook } = useActions(notebookPanelLogic)

    const hasFilters = !!search || createdByFilter.length > 0 || accountFilter !== null

    const columns: LemonTableColumns<AccountNoteApi> = [
        {
            title: 'Title',
            dataIndex: 'title',
            width: '100%',
            render: function Render(_, note) {
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
                        {note.title || 'Untitled'}
                    </Link>
                )
            },
        },
        {
            title: 'Account',
            dataIndex: 'account_name',
            render: function Render(_, note) {
                return (
                    <Link
                        data-attr="account-note-account"
                        to={urls.customerAnalyticsAccount(note.account_id)}
                        className="whitespace-nowrap"
                        onClick={() => {
                            posthog.capture(AccountsEvents.NotesTabAccountClicked, { account_id: note.account_id })
                        }}
                    >
                        {note.account_name}
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
            <div className="flex flex-wrap gap-2 items-center">
                <LemonInput
                    type="search"
                    placeholder="Search notes"
                    onChange={setSearch}
                    value={search}
                    size="small"
                    className="min-w-64"
                    data-attr="account-notes-search"
                />
                <AccountPicker />
                <CreatedByPicker
                    value={createdByFilter}
                    onChange={(userIds) => {
                        setCreatedByFilter(userIds)
                        reportFilterChange('created_by')
                    }}
                />
                <LemonCheckbox
                    checked={createdByCurrentUser}
                    onChange={(value) => {
                        setCreatedByCurrentUser(value)
                        reportFilterChange('my_notes')
                    }}
                    label="My notes"
                    info="Shortcut for Created by: you — notes you created"
                    data-attr="account-notes-my-notes-filter"
                />
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

function CreatedByPicker({ value, onChange }: { value: number[]; onChange: (userIds: number[]) => void }): JSX.Element {
    const buttonLabel =
        value.length === 0
            ? 'Created by anyone'
            : value.length === 1
              ? 'Created by 1 person'
              : `Created by ${value.length} people`
    return (
        <div className="flex gap-1 items-center" data-attr="account-notes-created-by-filter">
            <LemonDropdown
                closeOnClickInside={false}
                overlay={
                    <div className="p-2 min-w-64">
                        <MemberSelectMultiple
                            idKey="id"
                            value={value}
                            onChange={(users) => onChange(users.map((user) => user.id))}
                        />
                    </div>
                }
            >
                <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                    {buttonLabel}
                </LemonButton>
            </LemonDropdown>
            {value.length > 0 && (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconX />}
                    onClick={() => onChange([])}
                    tooltip="Clear created-by filter"
                />
            )}
        </div>
    )
}

function AccountPicker(): JSX.Element {
    const { accountFilter, accountSearch, accountOptions, accountOptionsResponseLoading } = useValues(accountNotesLogic)
    const { setAccountFilter, setAccountSearch, reportFilterChange } = useActions(accountNotesLogic)
    const [showPopover, setShowPopover] = useState(false)

    const selectAccount = (account: { id: string; name: string } | null): void => {
        setShowPopover(false)
        setAccountFilter(account)
        reportFilterChange('account')
    }

    return (
        <div className="flex gap-1 items-center" data-attr="account-notes-account-filter">
            <LemonDropdown
                closeOnClickInside={false}
                visible={showPopover}
                placement="bottom-start"
                actionable
                onVisibilityChange={(visible) => {
                    setShowPopover(visible)
                    if (!visible && accountSearch) {
                        setAccountSearch('')
                    }
                }}
                overlay={
                    <div className="max-w-100 space-y-2">
                        <LemonInput
                            type="search"
                            placeholder="Search accounts"
                            autoFocus
                            value={accountSearch}
                            onChange={setAccountSearch}
                            fullWidth
                        />
                        <ul className="space-y-px max-h-80 overflow-y-auto">
                            <li>
                                <LemonButton
                                    fullWidth
                                    role="menuitem"
                                    size="small"
                                    active={accountFilter === null}
                                    onClick={() => selectAccount(null)}
                                >
                                    All accounts
                                </LemonButton>
                            </li>
                            {accountOptions.map((option) => (
                                <li key={option.key}>
                                    <LemonButton
                                        fullWidth
                                        role="menuitem"
                                        size="small"
                                        active={accountFilter?.id === option.key}
                                        onClick={() => selectAccount({ id: option.key, name: option.label })}
                                    >
                                        {option.label}
                                    </LemonButton>
                                </li>
                            ))}
                            {accountOptionsResponseLoading ? (
                                <div className="p-2 text-secondary italic truncate border-t">Loading...</div>
                            ) : accountOptions.length === 0 ? (
                                <div className="p-2 text-secondary italic truncate border-t">
                                    {accountSearch ? 'No matches' : 'No accounts'}
                                </div>
                            ) : null}
                        </ul>
                    </div>
                }
            >
                <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                    {accountFilter ? accountFilter.name : 'All accounts'}
                </LemonButton>
            </LemonDropdown>
            {accountFilter !== null && (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconX />}
                    onClick={() => selectAccount(null)}
                    tooltip="Clear account filter"
                />
            )}
        </div>
    )
}
