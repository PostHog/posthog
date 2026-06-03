import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, Link, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { fullName } from 'lib/utils'
import { urls } from 'scenes/urls'

import type { AccountNotebookApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountNotebooksLogic } from './accountNotebooksLogic'

const PREVIEW_MAX_CHARS = 200

function getPreview(notebook: AccountNotebookApi): string {
    const text = (notebook.text_content ?? '').trim()
    if (!text) {
        return ''
    }
    const collapsed = text.replace(/\s+/g, ' ')
    return collapsed.length > PREVIEW_MAX_CHARS ? `${collapsed.slice(0, PREVIEW_MAX_CHARS).trimEnd()}…` : collapsed
}

export function AccountNotebooksExpansion({ accountId }: { accountId: string }): JSX.Element {
    const logic = accountNotebooksLogic({ accountId })
    const { notebooks, notebooksLoading } = useValues(logic)

    const columns: LemonTableColumns<AccountNotebookApi> = [
        {
            title: 'Note',
            key: 'title',
            render: (_, notebook) => {
                const preview = getPreview(notebook)
                return (
                    <div className="flex flex-col gap-1 py-1 max-w-2xl">
                        <Link to={urls.notebook(notebook.short_id)} className="font-medium">
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
            width: 220,
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
            width: 180,
            render: (_, notebook) => <TZLabel time={notebook.created_at} />,
        },
    ]

    return (
        <div className="sticky left-0 w-[100cqw] p-3 bg-bg-light">
            <LemonTable<AccountNotebookApi>
                size="small"
                embedded
                dataSource={notebooks ?? []}
                rowKey="short_id"
                loading={notebooksLoading}
                columns={columns}
                emptyState={
                    notebooks === null ? 'Failed to load account notes.' : 'No notes linked to this account yet.'
                }
            />
        </div>
    )
}
