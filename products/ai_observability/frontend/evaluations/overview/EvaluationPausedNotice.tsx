import { useActions, useValues } from 'kea'

import { IconPause, IconPlay } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import { lastResultDay } from './evaluationOverviewDisplay'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

/** Turning an evaluation off is a normal choice, so this offers the way back without pressing it. */
export function EvaluationPausedNotice({ row }: { row: EvaluationResultApi }): JSX.Element {
    const { configById, togglingIds, timezone } = useValues(evaluationsOverviewLogic)
    const { canEnableEvaluation } = useValues(llmEvaluationsLogic)
    const { toggleEvaluationEnabled } = useActions(llmEvaluationsLogic)
    const config = configById.get(row.id)
    const day = lastResultDay(row, timezone)

    return (
        <div className="flex flex-wrap items-center justify-between gap-3 border rounded bg-surface-primary px-4 py-3">
            <div className="flex items-center gap-2 text-secondary">
                <IconPause className="shrink-0" />
                <span>
                    {`Paused. New generations aren't scored while it's off.${day ? ` Last result ${day}.` : ''}`}
                </span>
            </div>
            {config && (
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPlay />}
                    onClick={() => toggleEvaluationEnabled(config.id)}
                    loading={togglingIds.includes(config.id)}
                    disabledReason={
                        getAccessControlDisabledReason(
                            AccessControlResourceType.Evaluation,
                            AccessControlLevel.Editor,
                            config.user_access_level ?? undefined
                        ) ??
                        (canEnableEvaluation(config) ? undefined : 'Add a provider API key to enable this evaluation.')
                    }
                    data-attr="evaluation-overview-drawer-resume"
                >
                    Turn back on
                </LemonButton>
            )}
        </div>
    )
}
