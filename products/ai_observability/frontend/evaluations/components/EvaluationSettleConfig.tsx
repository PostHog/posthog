import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { DurationPicker } from 'lib/components/DurationPicker/DurationPicker'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { settleStrategy } from '../constants'
import {
    DEFAULT_SESSION_MAX_AGE_SECONDS,
    DEFAULT_SESSION_QUIET_PERIOD_SECONDS,
    DEFAULT_SESSION_WINDOW_SECONDS,
    DEFAULT_TRACE_MAX_AGE_SECONDS,
    DEFAULT_TRACE_QUIET_PERIOD_SECONDS,
    DEFAULT_TRACE_WINDOW_SECONDS,
    llmEvaluationLogic,
} from '../llmEvaluationLogic'
import { EvaluationSettleStrategy } from '../types'

/** When a trace or session evaluation runs: after a fixed delay, or once the trace or session goes quiet. */
export function EvaluationSettleConfig(): JSX.Element | null {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setSettleStrategy, patchTargetConfig } = useActions(llmEvaluationLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const settlingStrategyEnabled = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVAL_SETTLING_STRATEGY]

    if (!evaluation || (evaluation.target !== 'trace' && evaluation.target !== 'session')) {
        return null
    }
    const isSessionTarget = evaluation.target === 'session'
    // Read the stored strategy whether or not the flag is on. The flag gates the picker, not what the row contains.
    const effectiveStrategy = settleStrategy(evaluation.target_config.strategy, evaluation.target)

    return (
        <>
            {settlingStrategyEnabled && (
                <LemonField.Pure label="Evaluate when">
                    <LemonSelect<EvaluationSettleStrategy>
                        value={effectiveStrategy}
                        onChange={setSettleStrategy}
                        options={[
                            {
                                value: 'fixed_window',
                                label: 'A fixed delay has passed',
                            },
                            {
                                value: 'inactivity',
                                label: isSessionTarget ? 'The session goes quiet' : 'The trace goes quiet',
                            },
                        ]}
                        fullWidth
                    />
                </LemonField.Pure>
            )}
            {effectiveStrategy === 'fixed_window' ? (
                <LemonField.Pure label="Wait before evaluating">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <DurationPicker
                            value={
                                evaluation.target_config.window_seconds ??
                                (isSessionTarget ? DEFAULT_SESSION_WINDOW_SECONDS : DEFAULT_TRACE_WINDOW_SECONDS)
                            }
                            onChange={(value) => {
                                if (evaluation.target_config.strategy === 'inactivity') {
                                    setSettleStrategy('fixed_window')
                                }
                                patchTargetConfig({
                                    window_seconds: value,
                                })
                            }}
                        />
                        <p className="text-muted text-xs mb-0 flex-1 basis-60">
                            {isSessionTarget
                                ? 'After the first matching generation, from 10 seconds to 7 days. Runs already scheduled keep the wait they started with.'
                                : 'After the first matching generation, from 10 seconds to 2 hours. Runs already scheduled keep the wait they started with.'}
                        </p>
                    </div>
                </LemonField.Pure>
            ) : (
                <>
                    <LemonField.Pure label="Quiet period">
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <DurationPicker
                                value={
                                    evaluation.target_config.quiet_period_seconds ??
                                    (isSessionTarget
                                        ? DEFAULT_SESSION_QUIET_PERIOD_SECONDS
                                        : DEFAULT_TRACE_QUIET_PERIOD_SECONDS)
                                }
                                onChange={(value) =>
                                    patchTargetConfig({
                                        quiet_period_seconds: value,
                                    })
                                }
                            />
                            <p className="text-muted text-xs mb-0 flex-1 basis-60">
                                {isSessionTarget
                                    ? 'Evaluate once the session has had no new activity for this long (10s to 24 hours). Sessions often pause for a while mid-conversation, so a longer quiet period means fewer verdicts on a session that was not finished.'
                                    : 'Evaluate once the trace has had no new activity for this long (10 seconds to 30 minutes).'}
                            </p>
                        </div>
                    </LemonField.Pure>
                    <LemonField.Pure label="Evaluate by">
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <DurationPicker
                                value={
                                    evaluation.target_config.max_age_seconds ??
                                    (isSessionTarget ? DEFAULT_SESSION_MAX_AGE_SECONDS : DEFAULT_TRACE_MAX_AGE_SECONDS)
                                }
                                onChange={(value) =>
                                    patchTargetConfig({
                                        max_age_seconds: value,
                                    })
                                }
                            />
                            <p className="text-muted text-xs mb-0 flex-1 basis-60">
                                {isSessionTarget
                                    ? 'Always evaluate once the session is this old, even if it is still active (1m to 7 days).'
                                    : "Always evaluate once the trace is this old, even if it's still active (1 minute to 2 hours)."}
                            </p>
                        </div>
                    </LemonField.Pure>
                </>
            )}
        </>
    )
}
