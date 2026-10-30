import { useActions, useValues } from 'kea'

import { IconEllipsis, IconFolder, IconPause, IconPencil, IconPlay, IconTrash, IconWarning } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import type { EvaluationConfig } from '../types'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

export function EvaluationResultActions({ config }: { config: EvaluationConfig }): JSX.Element {
    const { evaluationDirectories, movingEvaluationId, canEnableEvaluation } = useValues(llmEvaluationsLogic)
    const { toggleEvaluationEnabled, moveEvaluation, deleteEvaluation } = useActions(llmEvaluationsLogic)
    const { togglingIds, evaluationUrl } = useValues(evaluationsOverviewLogic)
    const { trackTableAction } = useActions(evaluationsOverviewLogic)
    const editorReason = getAccessControlDisabledReason(
        AccessControlResourceType.Evaluation,
        AccessControlLevel.Editor,
        config.user_access_level ?? undefined
    )
    const moving = movingEvaluationId === config.id
    const toggling = togglingIds.includes(config.id)
    const errored = config.status === 'error'
    const blocked = !config.enabled && !canEnableEvaluation(config)

    return (
        <div className="flex gap-1">
            <LemonButton
                size="small"
                icon={<IconPencil />}
                tooltip="Edit"
                to={evaluationUrl(config.id)}
                onClick={() => trackTableAction('edit')}
                disabledReason={editorReason}
                data-attr="evaluation-overview-table-edit"
            />
            <LemonMenu
                items={[
                    {
                        items: [
                            errored
                                ? {
                                      label: 'Open to fix',
                                      icon: <IconWarning />,
                                      to: evaluationUrl(config.id),
                                      'data-attr': 'evaluation-overview-table-fix',
                                  }
                                : {
                                      label: config.enabled ? 'Disable' : 'Enable',
                                      icon: config.enabled ? <IconPause /> : <IconPlay />,
                                      onClick: () => toggleEvaluationEnabled(config.id),
                                      disabledReason:
                                          editorReason ??
                                          (toggling
                                              ? 'Saving the change'
                                              : blocked
                                                ? 'Add a provider API key to enable this evaluation.'
                                                : undefined),
                                      'data-attr': 'evaluation-overview-table-toggle',
                                  },
                            {
                                label: 'Move to directory',
                                icon: <IconFolder />,
                                disabledReason: editorReason ?? (moving ? 'Moving the evaluation' : undefined),
                                items: [
                                    {
                                        label: 'Top level',
                                        onClick: () => moveEvaluation(config.id, null),
                                        disabledReason: config.directory_id ? undefined : 'Evaluation is already here',
                                    },
                                    ...evaluationDirectories.map((directory) => ({
                                        label: directory.name,
                                        onClick: () => moveEvaluation(config.id, directory.id),
                                        disabledReason:
                                            config.directory_id === directory.id
                                                ? 'Evaluation is already here'
                                                : undefined,
                                    })),
                                ],
                            },
                        ],
                    },
                    // A separate section draws a divider, which keeps the destructive action apart.
                    {
                        items: [
                            {
                                label: 'Delete',
                                icon: <IconTrash />,
                                status: 'danger',
                                disabledReason: editorReason,
                                'data-attr': 'evaluation-overview-table-delete',
                                onClick: () =>
                                    LemonDialog.open({
                                        title: `Delete ${config.name}?`,
                                        description: 'Are you sure you want to delete this evaluation?',
                                        primaryButton: {
                                            children: 'Delete',
                                            type: 'primary',
                                            status: 'danger',
                                            'data-attr': 'confirm-delete-evaluation',
                                            onClick: () => deleteEvaluation(config.id),
                                        },
                                        secondaryButton: { children: 'Cancel', type: 'secondary' },
                                    }),
                            },
                        ],
                    },
                ]}
            >
                <LemonButton
                    size="small"
                    icon={<IconEllipsis />}
                    loading={moving || toggling}
                    tooltip="More actions"
                    data-attr="evaluation-overview-table-more"
                />
            </LemonMenu>
        </div>
    )
}
