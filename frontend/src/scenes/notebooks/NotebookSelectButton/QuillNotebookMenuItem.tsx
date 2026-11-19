import { Badge, DropdownMenuItem } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { TZLabel } from 'lib/components/TZLabel'

import { NotebookListItemType } from '../types'
import { SESSION_SUMMARY_PREFIX, isSessionSummaryTitle, stripSessionSummaryPrefix } from './NotebookSelectButton'

export function QuillNotebookMenuItem({
    notebook,
    onClick,
}: {
    notebook: NotebookListItemType
    onClick: () => void
}): JSX.Element {
    const isSessionSummary = isSessionSummaryTitle(notebook.title || undefined)
    const title =
        (isSessionSummary ? stripSessionSummaryPrefix(notebook.title || undefined) : notebook.title) ||
        `Untitled (${notebook.short_id})`
    const author = notebook.created_by?.first_name || notebook.created_by?.email || 'Unknown'

    return (
        <DropdownMenuItem
            onClick={onClick}
            description={
                <span className="ph-no-capture">
                    <span>{author} · </span>
                    <TZLabel time={notebook.last_modified_at ?? notebook.created_at} />
                </span>
            }
        >
            {notebook.created_by && (
                <QuillPersonAvatar name={notebook.created_by.first_name} email={notebook.created_by.email} size="xs" />
            )}
            <span className="truncate">{title}</span>
            {isSessionSummary && <Badge>{SESSION_SUMMARY_PREFIX}</Badge>}
        </DropdownMenuItem>
    )
}
