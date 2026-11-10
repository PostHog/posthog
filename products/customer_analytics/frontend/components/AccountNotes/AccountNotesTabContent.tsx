import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconChevronDown, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput, LemonSkeleton, ProfilePicture } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Link } from 'lib/lemon-ui/Link'
import { fullName } from 'lib/utils/strings'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'
import { urls } from 'scenes/urls'

import type { AccountNoteApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountsEvents } from '../Accounts/constants'
import { accountNotesLogic, sortingToOrdering } from './accountNotesLogic'
import { AccountNotesViewSelector } from './AccountNotesViewSelector'
import { NotesCreatedByFilter } from './NotesCreatedByFilter'
import { NotesTagsFilter } from './NotesTagsFilter'

export function AccountNotesTabContent(): JSX.Element {
    const {
        accountNotes,
        accountNotesResponse,
        accountNotesResponseLoading,
        search,
        createdByFilter,
        createdByCurrentUser,
        assignedToCurrentUser,
        accountFilter,
        tagsFilter,
        sorting,
        pagination,
        pendingNoteTags,
    } = useValues(accountNotesLogic)
    const {
        setSearch,
        setCreatedByFilter,
        setCreatedByCurrentUser,
        setAssignedToCurrentUser,
        setTagsFilter,
        setOrdering,
        reportFilterChange,
        updateNoteTags,
    } = useActions(accountNotesLogic)
    const { selectNotebook } = useActions(notebookPanelLogic)

    const hasFilters =
        !!search ||
        createdByFilter.length > 0 ||
        assignedToCurrentUser ||
        accountFilter !== null ||
        tagsFilter.length > 0

    const columns: LemonTableColumns<AccountNoteApi> = [
        {
            title: 'Title',
            key: 'title',
            dataIndex: 'title',
            width: '100%',
            sorter: true,
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
            key: 'account_name',
            dataIndex: 'account_name',
            sorter: true,
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
            title: 'Tags',
            key: 'tags',
            render: function Render(_, note) {
                const tags = [...note.tags]
                // The title column takes 100% of the width, so the cell holds its own minimum to keep tags on one line.
                return (
                    <div className="min-w-60">
                        <ObjectTags
                            tags={tags}
                            onChange={(newTags) => updateNoteTags(note, newTags)}
                            saving={!!pendingNoteTags[note.short_id]}
                            data-attr="account-note-tags"
                        />
                    </div>
                )
            },
        },
        {
            title: 'Created by',
            key: 'created_by',
            sorter: true,
            render: function Render(_, note) {
                const user = note.created_by
                if (!user) {
                    return <span className="text-muted">Unknown</span>
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
        {
            ...(atColumn<AccountNoteApi>('created_at', 'Created') as LemonTableColumn<
                AccountNoteApi,
                keyof AccountNoteApi | undefined
            >),
            key: 'created_at',
            sorter: true,
        },
        {
            ...(atColumn<AccountNoteApi>('last_modified_at', 'Last modified') as LemonTableColumn<
                AccountNoteApi,
                keyof AccountNoteApi | undefined
            >),
            key: 'last_modified_at',
            sorter: true,
        },
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
                <AccountNotesViewSelector />
                <AccountPicker />
                <NotesTagsFilter
                    value={tagsFilter}
                    onChange={(tags) => {
                        setTagsFilter(tags)
                        reportFilterChange('tag')
                    }}
                    data-attr="account-notes-tags-filter"
                />
                <NotesCreatedByFilter
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
                    info="Shortcut for Created by: you. Notes you created"
                    data-attr="account-notes-my-notes-filter"
                />
                <LemonCheckbox
                    checked={assignedToCurrentUser}
                    onChange={(value) => {
                        setAssignedToCurrentUser(value)
                        reportFilterChange('my_accounts')
                    }}
                    label="My accounts"
                    info="Notes on accounts where you are the CSM or account executive"
                    data-attr="account-notes-my-accounts-filter"
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
                    sorting={sorting}
                    onSort={(newSorting) => setOrdering(sortingToOrdering(newSorting))}
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
