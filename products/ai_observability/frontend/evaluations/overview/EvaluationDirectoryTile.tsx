import { useActions, useValues } from 'kea'

import { IconEllipsis, IconFolder } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import { type DirectoryTile, evaluationsOverviewLogic } from './evaluationsOverviewLogic'

export function EvaluationDirectoryTile({ tile, selected }: { tile: DirectoryTile; selected: boolean }): JSX.Element {
    const { deletingDirectoryId } = useValues(llmEvaluationsLogic)
    const { openRenameDirectory, deleteDirectory, selectDirectory } = useActions(llmEvaluationsLogic)
    const { openDirectory } = useActions(evaluationsOverviewLogic)
    const { directory, evaluationCount, needAttentionCount } = tile
    const editorReason = getAccessControlDisabledReason(AccessControlResourceType.Evaluation, AccessControlLevel.Editor)
    const deleting = deletingDirectoryId === directory.id

    return (
        <div
            className={cn(
                'relative flex items-center rounded-lg border transition-colors motion-reduce:transition-none',
                selected
                    ? 'border-accent bg-accent-highlight-secondary'
                    : 'border-primary bg-surface-primary hover:border-accent'
            )}
        >
            <button
                type="button"
                onClick={() => (selected ? selectDirectory(null) : openDirectory(directory.id))}
                aria-pressed={selected}
                className="flex flex-1 min-w-0 items-center gap-3 px-3 py-2 pr-9 text-left cursor-pointer rounded-lg"
                data-attr="evaluation-overview-directory-tile"
            >
                <span className="flex size-8 shrink-0 items-center justify-center rounded text-lg bg-accent-highlight-secondary text-accent">
                    <IconFolder />
                </span>
                <span className="flex flex-col min-w-0">
                    <span className="font-semibold truncate">{directory.name}</span>
                    <span className="text-xs text-secondary truncate">
                        <span>{pluralize(evaluationCount, 'evaluation')}</span>
                        {needAttentionCount ? (
                            <span className="text-danger">{` · ${needAttentionCount} need attention`}</span>
                        ) : null}
                    </span>
                </span>
            </button>
            <div className="absolute right-1 top-1/2 -translate-y-1/2">
                <LemonMenu
                    items={[
                        {
                            label: 'Rename',
                            onClick: () => openRenameDirectory(directory),
                            disabledReason: editorReason,
                            'data-attr': 'evaluation-overview-directory-rename',
                        },
                        {
                            label: 'Delete',
                            status: 'danger',
                            disabledReason: editorReason ?? (deleting ? 'Deleting the directory' : undefined),
                            'data-attr': 'evaluation-overview-directory-delete',
                            onClick: () =>
                                LemonDialog.open({
                                    title: `Delete ${directory.name}?`,
                                    description: `${pluralize(evaluationCount, 'evaluation')} will move to the top level.`,
                                    primaryButton: {
                                        children: 'Delete directory',
                                        status: 'danger',
                                        onClick: () => deleteDirectory(directory.id),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                }),
                        },
                    ]}
                >
                    <LemonButton
                        size="xsmall"
                        icon={<IconEllipsis />}
                        loading={deleting}
                        tooltip="Directory actions"
                        data-attr="evaluation-overview-directory-more"
                    />
                </LemonMenu>
            </div>
        </div>
    )
}
