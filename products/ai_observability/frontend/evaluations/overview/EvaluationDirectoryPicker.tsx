import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu, type LemonMenuItems } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { pluralize } from 'lib/utils/strings'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

export function EvaluationDirectoryPicker(): JSX.Element | null {
    const { directoryTiles, selectedDirectory } = useValues(evaluationsOverviewLogic)
    const { deletingDirectoryId } = useValues(llmEvaluationsLogic)
    const { openCreateDirectory, openRenameDirectory, deleteDirectory, selectDirectory } =
        useActions(llmEvaluationsLogic)
    const { openDirectory } = useActions(evaluationsOverviewLogic)
    const editorReason = getAccessControlDisabledReason(AccessControlResourceType.Evaluation, AccessControlLevel.Editor)

    // Few teams use directories, so the picker only appears once a team has made one.
    if (directoryTiles.length === 0) {
        return null
    }
    const selectedTile = directoryTiles.find((tile) => tile.directory.id === selectedDirectory?.id)

    const items: LemonMenuItems = [
        {
            items: [
                { label: 'All directories', active: !selectedDirectory, onClick: () => selectDirectory(null) },
                ...directoryTiles.map(({ directory, evaluationCount, needAttentionCount }) => ({
                    label: directory.name,
                    icon: <IconFolder />,
                    active: directory.id === selectedDirectory?.id,
                    sideIcon: (
                        <span className="text-xs text-secondary whitespace-nowrap">
                            {pluralize(evaluationCount, 'evaluation')}
                            {needAttentionCount ? (
                                <span className="text-danger">{` · ${needAttentionCount} need attention`}</span>
                            ) : null}
                        </span>
                    ),
                    onClick: () => openDirectory(directory.id),
                    'data-attr': 'evaluation-overview-directory-option',
                })),
            ],
        },
        {
            items: [
                ...(selectedTile
                    ? [
                          {
                              label: `Rename ${selectedTile.directory.name}`,
                              onClick: () => openRenameDirectory(selectedTile.directory),
                              disabledReason: editorReason,
                              'data-attr': 'evaluation-overview-directory-rename',
                          },
                          {
                              label: `Delete ${selectedTile.directory.name}`,
                              status: 'danger' as const,
                              disabledReason:
                                  editorReason ??
                                  (deletingDirectoryId === selectedTile.directory.id
                                      ? 'Deleting the directory'
                                      : undefined),
                              'data-attr': 'evaluation-overview-directory-delete',
                              onClick: () =>
                                  LemonDialog.open({
                                      title: `Delete ${selectedTile.directory.name}?`,
                                      description: `${pluralize(selectedTile.evaluationCount, 'evaluation')} will move to the top level.`,
                                      primaryButton: {
                                          children: 'Delete directory',
                                          status: 'danger',
                                          onClick: () => deleteDirectory(selectedTile.directory.id),
                                      },
                                      secondaryButton: { children: 'Cancel' },
                                  }),
                          },
                      ]
                    : []),
                {
                    label: 'New directory',
                    onClick: () => openCreateDirectory(),
                    disabledReason: editorReason,
                    'data-attr': 'create-evaluation-directory-button',
                },
            ],
        },
    ]

    return (
        <LemonMenu items={items}>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconFolder />}
                data-attr="evaluation-overview-directory-picker"
            >
                {selectedDirectory?.name ?? 'All directories'}
            </LemonButton>
        </LemonMenu>
    )
}
