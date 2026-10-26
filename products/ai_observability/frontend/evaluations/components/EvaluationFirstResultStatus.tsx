import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { VOLUME_LOOKBACK_DAYS, runRate } from '../evaluationVolume'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { DEFAULT_SESSION_WINDOW_SECONDS, DEFAULT_TRACE_WINDOW_SECONDS, llmEvaluationLogic } from '../llmEvaluationLogic'
import type { EvaluationConfig } from '../types'

const UNIT_NOUNS = { generation: 'generations', trace: 'traces', session: 'sessions' } as const

/**
 * Says why a new evaluation has no results yet: it is paused, nothing matches its triggers, or the first run is
 * on its way. Shows only while the default range holds no runs at all and the evaluation is younger than that range,
 * because only then does it mean the evaluation has never run.
 */
export function EvaluationFirstResultStatus(): JSX.Element | null {
    const { originalEvaluation, runsStats, runsStatsLoading, runsBackfillId, runsDateRange } =
        useValues(llmEvaluationLogic)
    const { props } = useMountedLogic(llmEvaluationLogic)

    const neverRan =
        !!originalEvaluation &&
        !runsStatsLoading &&
        runsStats?.total === 0 &&
        !runsBackfillId &&
        runsDateRange.date_from === `-${VOLUME_LOOKBACK_DAYS}d` &&
        !runsDateRange.date_to &&
        dayjs(originalEvaluation.created_at).isAfter(dayjs().subtract(VOLUME_LOOKBACK_DAYS, 'day'))
    if (!neverRan || !originalEvaluation) {
        return null
    }
    return (
        <BindLogic logic={evaluationVolumeLogic} props={props}>
            <div>
                <FirstResultBanner evaluation={originalEvaluation} />
            </div>
        </BindLogic>
    )
}

function FirstResultBanner({ evaluation }: { evaluation: EvaluationConfig }): JSX.Element {
    const { volume } = useValues(evaluationVolumeLogic)
    const { setActiveTab } = useActions(llmEvaluationLogic)
    const target = evaluation.evaluation_type === 'sentiment' ? 'generation' : evaluation.target
    const units = UNIT_NOUNS[target]
    const toTriggers = {
        children: 'Check the triggers',
        onClick: () => setActiveTab('configuration'),
        'data-attr': 'llma-evaluation-first-result-triggers',
    }

    if (!evaluation.enabled) {
        return (
            <LemonBanner type="info" className="mb-4" action={{ ...toTriggers, children: 'Open configuration' }}>
                <span className="font-semibold">No results yet, because this evaluation is paused.</span> Turn it on in
                its configuration to start checking new {units}.
            </LemonBanner>
        )
    }
    if (volume && volume.runs === 0) {
        return (
            <LemonBanner type="warning" className="mb-4" action={toTriggers}>
                <span className="font-semibold">No results yet.</span> Nothing matched its triggers in the last{' '}
                {VOLUME_LOOKBACK_DAYS} days, so it runs only once matching {units} arrive.
            </LemonBanner>
        )
    }
    const waitSeconds =
        target !== 'generation' && (evaluation.target_config.strategy ?? 'fixed_window') === 'fixed_window'
            ? (evaluation.target_config.window_seconds ??
              (target === 'session' ? DEFAULT_SESSION_WINDOW_SECONDS : DEFAULT_TRACE_WINDOW_SECONDS))
            : null
    return (
        <LemonBanner type="info" className="mb-4">
            <span className="font-semibold">Waiting for the first result.</span>
            {volume && ` At the traffic of the last ${VOLUME_LOOKBACK_DAYS} days, it runs ${runRate(volume.runs)}.`}
            {waitSeconds !== null &&
                ` Each ${target} gets ${humanFriendlyDuration(waitSeconds)} after its first generation before it runs.`}
        </LemonBanner>
    )
}
