import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { VOLUME_LOOKBACK_DAYS } from '../evaluationVolume'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'

/** For a new evaluation: whether it also runs on the last days of traffic once created, or why it starts paused. */
export function EvaluationPastTrafficOption(): JSX.Element | null {
    const { evaluation, checkPastTraffic } = useValues(llmEvaluationLogic)
    const { setCheckPastTraffic } = useActions(llmEvaluationLogic)
    const { volume } = useValues(evaluationVolumeLogic)

    if (!evaluation) {
        return null
    }
    if (!evaluation.enabled) {
        return (
            <p className="mb-0 text-xs text-secondary">
                It starts paused until you add a provider API key. Then turn it on from its page.
            </p>
        )
    }
    // Unknown volume (still counting, or a filter on content) still offers it; only a known zero hides it.
    if (volume?.runs === 0) {
        return null
    }
    const units = volume ? pluralize(volume.matchingUnits, volume.target) : null
    // Below 100% sampling the exact count depends on which units the sample picks, so it names the pool instead.
    const count = !volume
        ? ''
        : volume.runs === volume.matchingUnits
          ? ` It will evaluate ${units}.`
          : ` It will evaluate a sample of the ${units} that matched.`
    return (
        <LemonCheckbox
            checked={checkPastTraffic}
            onChange={setCheckPastTraffic}
            label={
                <span className="flex items-center gap-1">
                    {`Also evaluate the last ${VOLUME_LOOKBACK_DAYS} days`}
                    <Tooltip
                        title={`See results right away instead of waiting for new traffic.${count}${
                            evaluation.evaluation_type === 'llm_judge'
                                ? ' Each one will be a call to your judge model.'
                                : ''
                        }`}
                    >
                        <IconInfo className="text-secondary" />
                    </Tooltip>
                </span>
            }
            size="small"
            data-attr="llma-evaluation-create-past-traffic"
        />
    )
}
