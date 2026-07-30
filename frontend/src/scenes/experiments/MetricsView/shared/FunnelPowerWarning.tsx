import { IconWarning } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { FunnelPowerRisk } from '~/queries/schema/schema-general'

/**
 * A funnel metric counts completions of the final step over everyone exposed, so a narrow
 * step earlier in the funnel leaves a low conversion rate with a wide noise band. Without
 * this the results view shows a delta and an interval that read like a real move.
 */
export function FunnelPowerWarning({ powerRisk }: { powerRisk: FunnelPowerRisk }): JSX.Element {
    const stepShare = `${powerRisk.narrowest_step_percentage.toFixed(1)}%`

    return (
        <Tooltip
            title={
                <div className="deprecated-space-y-2">
                    <div>
                        Only {stepShare} of exposed users reach step {powerRisk.narrowest_step}, so this metric is a low
                        conversion rate measured over everyone in the experiment. Small differences between variants sit
                        inside the noise.
                    </div>
                    <div>
                        Detecting a {powerRisk.minimum_detectable_effect}% change at this conversion rate takes around{' '}
                        {humanFriendlyLargeNumber(powerRisk.recommended_sample_size)} exposures. You have{' '}
                        {humanFriendlyLargeNumber(powerRisk.observed_exposures)} so far.
                    </div>
                    <div>
                        To measure the later steps on their own, add a version of this metric that starts after the
                        narrow step.
                    </div>
                </div>
            }
        >
            <div className="flex items-center gap-1 text-xs text-warning mt-1 w-fit">
                <IconWarning className="shrink-0" />
                <span>Too few users for a reliable result</span>
            </div>
        </Tooltip>
    )
}
