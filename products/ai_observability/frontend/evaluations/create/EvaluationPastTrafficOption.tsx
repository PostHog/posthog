import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { VOLUME_LOOKBACK_DAYS, type VolumeEstimate } from '../evaluationVolume'

export function EvaluationPastTrafficOption({
    checked,
    onChange,
    volume,
    callsJudge,
}: {
    checked: boolean
    onChange: (checked: boolean) => void
    volume: VolumeEstimate | null
    callsJudge: boolean
}): JSX.Element {
    // Unknown volume still offers it. A known zero keeps the option in place and turns it off with the reason, so it
    // does not vanish and come back as the sampling changes.
    const nothingToEvaluate = volume?.runs === 0
    const units = volume ? pluralize(volume.matchingUnits, volume.target) : null
    // Below 100% sampling the exact count depends on which units the sample picks, so it names the pool instead.
    const count = !volume
        ? ''
        : volume.runs === volume.matchingUnits
          ? ` It will evaluate ${units}.`
          : ` It will evaluate a sample of the ${units} that matched.`
    return (
        <LemonCheckbox
            checked={checked && !nothingToEvaluate}
            onChange={onChange}
            disabledReason={
                nothingToEvaluate
                    ? `With these filters and this sampling, nothing from the last ${VOLUME_LOOKBACK_DAYS} days would be evaluated.`
                    : undefined
            }
            label={
                <span className="flex items-center gap-1">
                    {`Also evaluate the last ${VOLUME_LOOKBACK_DAYS} days`}
                    <Tooltip
                        title={`See results right away instead of waiting for new traffic.${count}${
                            callsJudge ? ' Each one will be a call to your judge model.' : ''
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
