import { useActions, useValues } from 'kea'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { VOLUME_LOOKBACK_DAYS, filtersOnContent, runRate } from '../evaluationVolume'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'

const UNIT_NOUNS = { trace: 'traces', session: 'sessions' } as const

/** How often the evaluation would have run last week, so a filter that matches nothing shows before saving. */
export function EvaluationVolumeEstimate(): JSX.Element | null {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setEvaluationTarget } = useActions(llmEvaluationLogic)
    const { volume, countsLoading, countsError } = useValues(evaluationVolumeLogic)

    if (countsError) {
        return <p className="mb-0 text-sm text-secondary">Couldn't estimate how often it would run.</p>
    }
    if (evaluation && filtersOnContent(evaluation.conditions)) {
        return (
            <p className="mb-0 text-sm text-secondary">
                Couldn't estimate how often it would run, because a filter checks the input or output.
            </p>
        )
    }
    if (!volume) {
        return countsLoading ? (
            <p className="mb-0 flex items-center gap-2 text-sm text-secondary">
                <Spinner />
                Counting matching generations
            </p>
        ) : null
    }
    if (volume.matchingGenerations === 0) {
        // The wrapper carries the data-attr, since LemonBanner does not pass one through.
        return (
            <div data-attr="llma-evaluation-create-volume-none">
                <LemonBanner type="warning">
                    {`No generations matched in the last ${VOLUME_LOOKBACK_DAYS} days, so it would not have run. Check the filters, or keep them if the traffic has not started yet.`}
                </LemonBanner>
            </div>
        )
    }
    if (volume.target !== 'generation' && volume.matchingUnits === 0) {
        const ids =
            volume.target === 'trace'
                ? 'a trace ID ($ai_trace_id)'
                : 'both a session ID ($ai_session_id) and a trace ID ($ai_trace_id)'
        return (
            <LemonBanner
                type="warning"
                action={{
                    children: 'Evaluate each generation',
                    onClick: () => setEvaluationTarget('generation'),
                    'data-attr': 'llma-evaluation-create-use-generation',
                }}
            >
                {`Generations matched, but none were sent with ${ids}, so this ${volume.target} evaluation would not run.`}
            </LemonBanner>
        )
    }
    const matched =
        volume.target === 'generation'
            ? `${humanFriendlyNumber(volume.matchingGenerations)} generations matched`
            : `${humanFriendlyNumber(volume.matchingGenerations)} generations in ${humanFriendlyNumber(volume.matchingUnits)} ${UNIT_NOUNS[volume.target]} matched`
    return (
        <div className="flex items-start gap-2 text-sm text-secondary" data-attr="llma-evaluation-create-volume">
            {countsLoading && <Spinner className="mt-0.5" />}
            <p className="mb-0">
                {`In the last ${VOLUME_LOOKBACK_DAYS} days, ${matched}. With this sampling it would have run about ${humanFriendlyNumber(volume.runs)} times, ${runRate(volume.runs)}.`}
                {evaluation?.evaluation_type === 'llm_judge' && ' Each run is one call to your judge model.'}
            </p>
        </div>
    )
}
