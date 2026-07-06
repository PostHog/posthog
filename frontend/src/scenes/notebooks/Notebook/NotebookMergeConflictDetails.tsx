import { useActions, useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { MarkdownTextDiff } from 'lib/components/MarkdownNotebook'
import type { NotebookCollaborationConflict } from 'lib/components/MarkdownNotebook'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { notebookLogic } from './notebookLogic'

function ConflictItem({ conflict }: { conflict: NotebookCollaborationConflict }): JSX.Element {
    const remoteDeleted = !conflict.remoteMarkdown
    const localDeleted = !conflict.localMarkdown

    return (
        <div className="border rounded overflow-hidden">
            <div className="flex items-center justify-between gap-2 p-2 border-b bg-surface-secondary">
                <span className="text-xs font-medium text-secondary">
                    {remoteDeleted
                        ? 'A collaborator deleted this block — your edit was kept'
                        : localDeleted
                          ? 'You deleted this block — a collaborator edited it, and your deletion was kept'
                          : 'You both edited this block — your version was kept'}
                </span>
                {!remoteDeleted && (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconCopy />}
                        onClick={() => void copyToClipboard(conflict.remoteMarkdown, "the collaborator's version")}
                    >
                        Copy their version
                    </LemonButton>
                )}
            </div>
            <div className="p-3 max-h-60 overflow-y-auto overflow-x-hidden break-words font-mono text-sm">
                <MarkdownTextDiff before={conflict.remoteMarkdown} after={conflict.localMarkdown} />
            </div>
        </div>
    )
}

export function NotebookMergeConflictDetails(): JSX.Element {
    const { markdownMergeConflictDetails } = useValues(notebookLogic)
    const { dismissMarkdownMergeConflictDetails } = useActions(notebookLogic)

    return (
        <LemonModal
            isOpen={!!markdownMergeConflictDetails}
            onClose={dismissMarkdownMergeConflictDetails}
            title="Review merge conflicts"
            description="These edits couldn't be merged automatically, so your version is showing. The collaborator's conflicting text is below in case you want to recover it."
            footer={
                <LemonButton type="primary" onClick={dismissMarkdownMergeConflictDetails}>
                    Close
                </LemonButton>
            }
            width={720}
        >
            <div className="flex flex-col gap-3">
                <div className="flex gap-4 text-xs text-secondary">
                    <span>
                        <del className="text-danger bg-danger-highlight line-through">A collaborator wrote</del>
                    </span>
                    <span>
                        <ins className="text-success bg-success-highlight no-underline">Your version (kept)</ins>
                    </span>
                </div>
                {(markdownMergeConflictDetails ?? []).map((conflict, index) => (
                    <ConflictItem key={`${conflict.nodeId}-${index}`} conflict={conflict} />
                ))}
            </div>
        </LemonModal>
    )
}
