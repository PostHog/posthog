import { useActions, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconCalendar, IconGear, IconClockRewind, IconPlay } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import { statusReasonLabel, statusReasonRecoveryLabel } from '../statusDisplay'
import type { EvaluationStatusReason } from '../types'
import { evaluationResultDrawerLogic } from './evaluationResultDrawerLogic'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

const HedgehogSearching = pngHoggie(magnifyingGlassPng)

/** The range the "Widen the range" action switches to, and the length below which it offers to. */
const WIDER_RANGE = '-30d'
const WIDER_RANGE_DAYS = 30

/** What the drawer shows when an evaluation graded nothing in the range, with the next steps for its state. */
export function EvaluationDrawerEmptyState({ row }: { row: EvaluationResultApi }): JSX.Element {
    const { configById, togglingIds, interval, periodLength, evaluationUrl } = useValues(evaluationsOverviewLogic)
    const { canEnableEvaluation } = useValues(llmEvaluationsLogic)
    const { toggleEvaluationEnabled, setDates } = useActions(llmEvaluationsLogic)
    const { trackEmptyStateAction } = useActions(evaluationResultDrawerLogic)
    const config = configById.get(row.id)
    const errored = row.attentionReasons.includes('errored')
    const enabled = config?.enabled ?? row.enabled
    const reason = row.statusReason as EvaluationStatusReason | null
    const editorReason = getAccessControlDisabledReason(
        AccessControlResourceType.Evaluation,
        AccessControlLevel.Editor,
        config?.user_access_level ?? undefined
    )
    const state = errored ? 'errored' : enabled ? 'enabled' : 'disabled'

    const title = errored ? statusReasonLabel(reason) : 'Nothing graded in this range'
    const explanation = errored
        ? statusReasonRecoveryLabel(reason)
        : enabled
          ? 'No generations matched its triggers in this range.'
          : "It's turned off, so new generations aren't scored."

    const runOnPastData = (
        <LemonButton
            type="secondary"
            icon={<IconClockRewind />}
            to={evaluationUrl(row.id, { evaluation_tab: 'backfills' })}
            onClick={() => trackEmptyStateAction('run_on_past_data', state)}
            disabledReason={editorReason}
            data-attr="evaluation-overview-drawer-empty-backfill"
        >
            Run on past data
        </LemonButton>
    )

    return (
        <div className="flex flex-col items-center justify-center gap-3 text-center py-12 px-4">
            <HedgehogSearching className="w-28 h-28" />
            <h3 className="mb-0 text-lg font-semibold">{title}</h3>
            <p className="mb-0 text-secondary max-w-md">{explanation}</p>
            <div className="flex flex-wrap justify-center gap-2 pt-1">
                {errored ? (
                    <>
                        {reason?.startsWith('provider_key') ? (
                            <LemonButton
                                type="primary"
                                icon={<IconGear />}
                                to={urls.settings('project-ai-observability', 'ai-observability-byok')}
                                onClick={() => trackEmptyStateAction('fix_in_settings', state)}
                                data-attr="evaluation-overview-drawer-empty-settings"
                            >
                                Fix in settings
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="primary"
                                to={evaluationUrl(row.id, { evaluation_tab: 'configuration' })}
                                onClick={() => trackEmptyStateAction('fix_evaluation', state)}
                                disabledReason={editorReason}
                                data-attr="evaluation-overview-drawer-empty-fix"
                            >
                                Fix the evaluation
                            </LemonButton>
                        )}
                        <LemonButton
                            type="secondary"
                            to={evaluationUrl(row.id)}
                            onClick={() => trackEmptyStateAction('open_evaluation', state)}
                            data-attr="evaluation-overview-drawer-empty-open"
                        >
                            Open evaluation
                        </LemonButton>
                    </>
                ) : !enabled ? (
                    <>
                        {config && (
                            <LemonButton
                                type="primary"
                                icon={<IconPlay />}
                                onClick={() => {
                                    trackEmptyStateAction('turn_on', state)
                                    toggleEvaluationEnabled(config.id)
                                }}
                                loading={togglingIds.includes(config.id)}
                                disabledReason={
                                    editorReason ??
                                    (canEnableEvaluation(config)
                                        ? undefined
                                        : 'Add a provider API key to enable this evaluation.')
                                }
                                data-attr="evaluation-overview-drawer-empty-turn-on"
                            >
                                Turn it back on
                            </LemonButton>
                        )}
                        {runOnPastData}
                    </>
                ) : (
                    <>
                        <LemonButton
                            type="primary"
                            to={evaluationUrl(row.id, { evaluation_tab: 'configuration' })}
                            onClick={() => trackEmptyStateAction('check_triggers', state)}
                            data-attr="evaluation-overview-drawer-empty-triggers"
                        >
                            Check the triggers
                        </LemonButton>
                        {(interval === 'hour' || periodLength < WIDER_RANGE_DAYS) && (
                            <LemonButton
                                type="secondary"
                                icon={<IconCalendar />}
                                onClick={() => {
                                    trackEmptyStateAction('widen_range', state)
                                    setDates(WIDER_RANGE, null)
                                }}
                                data-attr="evaluation-overview-drawer-empty-widen"
                            >
                                Widen the range
                            </LemonButton>
                        )}
                        {runOnPastData}
                    </>
                )}
            </div>
        </div>
    )
}
