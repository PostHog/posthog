import { useActions, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCloud, IconGraph, IconPencil, IconPeople, IconPiggyBank, IconReceipt } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonLabel,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTabs,
    Link,
    ProfilePicture,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { IconSlack } from 'lib/lemon-ui/icons'
import { fullName } from 'lib/utils/strings'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'
import { urls } from 'scenes/urls'

import type { AccountNotebookApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountBillingExpansion } from './AccountBillingExpansion'
import { accountBillingLogic } from './accountBillingLogic'
import { accountLinksLogic } from './accountLinksLogic'
import { accountNotebooksLogic } from './accountNotebooksLogic'
import { AccountOpportunitiesExpansion } from './AccountOpportunitiesExpansion'
import { accountOpportunitiesLogic } from './accountOpportunitiesLogic'
import { AccountRelatedUsersExpansion } from './AccountRelatedUsersExpansion'
import { accountRelatedUsersLogic } from './accountRelatedUsersLogic'
import { AccountRelationshipsExpansion } from './AccountRelationshipsExpansion'
import { accountRelationshipsLogic } from './accountRelationshipsLogic'
import { accountsExpansionLogic } from './accountsExpansionLogic'
import { AccountsEvents } from './constants'
import { EditAccountLinksButton } from './EditAccountLinksButton'

const PREVIEW_MAX_CHARS = 200

function getPreview(notebook: AccountNotebookApi): string {
    const text = (notebook.text_content ?? '').trim()
    if (!text) {
        return ''
    }
    const collapsed = text.replace(/\s+/g, ' ')
    return collapsed.length > PREVIEW_MAX_CHARS ? `${collapsed.slice(0, PREVIEW_MAX_CHARS).trimEnd()}…` : collapsed
}

const LINK_ICONS: Record<string, JSX.Element> = {
    organization: <IconPeople />,
    revenue: <IconPiggyBank />,
    'usage-dashboard': <IconGraph />,
    slack: <IconSlack />,
    'billing-admin': <IconReceipt />,
    salesforce: <IconCloud />,
}

function ActiveRelationships({ accountId }: { accountId: string }): JSX.Element | null {
    const { activeRelationships } = useValues(accountRelationshipsLogic({ accountId }))
    if (activeRelationships.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-2">
            <h4 className="secondary uppercase text-secondary mb-0">Relationships</h4>
            {activeRelationships.map((relationship) => (
                <div key={relationship.id} className="flex flex-col gap-1">
                    <LemonLabel>{relationship.definition.name}</LemonLabel>
                    <div className="flex items-center gap-2 border rounded px-2 py-1.5 bg-bg-light">
                        {relationship.user ? (
                            <>
                                <ProfilePicture user={{ email: relationship.user.email }} size="sm" />
                                <span className="text-sm">{relationship.user.email}</span>
                            </>
                        ) : (
                            <span className="text-sm text-muted italic">Deleted user</span>
                        )}
                    </div>
                </div>
            ))}
        </div>
    )
}

function UsefulLinks({ accountId }: { accountId: string }): JSX.Element {
    const { links, accountLoading } = useValues(accountLinksLogic({ accountId }))
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1 mb-1">
                <h4 className="secondary uppercase text-secondary mb-0">Useful links</h4>
                <EditAccountLinksButton accountId={accountId} />
            </div>
            {accountLoading ? (
                <>
                    <LemonSkeleton className="h-7 w-32" />
                    <LemonSkeleton className="h-7 w-32" />
                    <LemonSkeleton className="h-7 w-32" />
                </>
            ) : (
                links.map((link) => (
                    <LemonButton
                        key={link.key}
                        type="tertiary"
                        size="small"
                        fullWidth
                        icon={LINK_ICONS[link.key]}
                        to={link.to ?? undefined}
                        targetBlank={link.targetBlank}
                        disabledReason={link.disabledReason ?? undefined}
                        onClick={() =>
                            posthog.capture(AccountsEvents.LinkClicked, {
                                link_key: link.key,
                                has_destination: !!link.to,
                            })
                        }
                    >
                        {link.label}
                    </LemonButton>
                ))
            )}
        </div>
    )
}

export function AccountNotebooksExpansion({
    accountId,
    externalId,
}: {
    accountId: string
    externalId: string
}): JSX.Element {
    const logic = accountNotebooksLogic({ accountId })
    const { notebooks, notebooksResponseLoading, createdNoteLoading, searchTerm, sorting, pagination } =
        useValues(logic)

    // LemonTabs only renders the active tab, so without this the data refetches on every tab switch.
    useMountedLogic(accountRelatedUsersLogic({ externalId }))
    useMountedLogic(accountRelationshipsLogic({ accountId }))
    useMountedLogic(accountBillingLogic({ accountId, externalId, kind: 'usage' }))
    useMountedLogic(accountBillingLogic({ accountId, externalId, kind: 'spend' }))
    useMountedLogic(accountOpportunitiesLogic({ accountId }))
    const { setSearchTerm, setSorting, createNote } = useActions(logic)
    const { activeTabFor } = useValues(accountsExpansionLogic)
    const { setActiveTab } = useActions(accountsExpansionLogic)
    const { selectNotebook } = useActions(notebookPanelLogic)
    const activeTab = activeTabFor(accountId)

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
        <div
            className="sticky left-0 w-[100cqw] max-w-full overflow-x-hidden p-3 bg-bg-light"
            data-attr="account-expansion"
        >
            <div className="flex gap-4">
                <div className="w-fit shrink-0 flex flex-col gap-4">
                    <UsefulLinks accountId={accountId} />
                    <ActiveRelationships accountId={accountId} />
                </div>
                <div className="flex-1 min-w-0">
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={(tab) => setActiveTab(accountId, tab)}
                        size="small"
                        tabs={[
                            {
                                key: 'notes',
                                label: 'Notes',
                                content: (
                                    <div className="flex flex-col gap-2">
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
                                            embedded
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
                                ),
                            },
                            {
                                key: 'users',
                                label: 'Users',
                                content: <AccountRelatedUsersExpansion externalId={externalId} />,
                            },
                            {
                                key: 'relationships',
                                label: 'Relationships',
                                content: <AccountRelationshipsExpansion accountId={accountId} />,
                            },
                            {
                                key: 'usage',
                                label: 'Usage',
                                content: (
                                    <AccountBillingExpansion
                                        accountId={accountId}
                                        externalId={externalId}
                                        kind="usage"
                                    />
                                ),
                            },
                            {
                                key: 'spend',
                                label: 'Spend',
                                content: (
                                    <AccountBillingExpansion
                                        accountId={accountId}
                                        externalId={externalId}
                                        kind="spend"
                                    />
                                ),
                            },
                            {
                                key: 'opportunities',
                                label: 'Opportunities',
                                content: <AccountOpportunitiesExpansion accountId={accountId} />,
                            },
                        ]}
                    />
                </div>
            </div>
        </div>
    )
}
