import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

import { accountNotebooksLogic } from './accountNotebooksLogic'

export function AccountNotebooksExpansion({ accountId }: { accountId: string }): JSX.Element {
    const logic = accountNotebooksLogic({ accountId })
    const { notebooks, notebooksLoading } = useValues(logic)

    if (notebooks === null || notebooksLoading) {
        return (
            <div className="flex items-center gap-2 p-3 text-muted">
                <Spinner />
                <span>Loading notebooks…</span>
            </div>
        )
    }

    if (notebooks.length === 0) {
        return <div className="p-3 text-muted">No notebooks linked to this account yet.</div>
    }

    return (
        <div className="p-3">
            <div className="text-xs uppercase tracking-wide text-muted mb-2">Notebooks</div>
            <ul className="flex flex-col gap-1">
                {notebooks.map((notebook) => (
                    <li key={notebook.short_id} className="flex items-center justify-between gap-3">
                        <Link to={urls.notebook(notebook.short_id)} className="font-medium">
                            {notebook.title || 'Untitled notebook'}
                        </Link>
                        <span className="text-xs text-muted">
                            {notebook.last_modified_by?.email
                                ? `${notebook.last_modified_by.email} · `
                                : ''}
                            {dayjs(notebook.last_modified_at).fromNow()}
                        </span>
                    </li>
                ))}
            </ul>
        </div>
    )
}
