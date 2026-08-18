import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { experimentLogic } from '../experimentLogic'
import { exposureCriteriaModalLogic } from './exposureCriteriaModalLogic'

// The backend already decided the warning is worth showing; this is only a display floor so we
// don't list a low, incidental share next to the one that actually drove the skew.
const COMPOSITION_SHARE_DISPLAY_FLOOR = 1

/**
 * Surfaces the botlike exposure composition behind a sample-ratio mismatch: the share of exposed
 * users with no user agent or no `$device_type` on their first exposure. The backend only emits
 * `exposure_composition_warning` when the split is off and that share is large, so presence of the
 * field is the gate.
 */
export function ExposureCompositionWarning(): JSX.Element | null {
    const { exposures, exposureCriteria } = useValues(experimentLogic)
    const { openExposureCriteriaModal } = useActions(exposureCriteriaModalLogic)

    const warning = exposures?.exposure_composition_warning

    if (!warning) {
        return null
    }

    const missingUserAgent = warning.missing_user_agent_percentage
    const missingDeviceType = warning.missing_device_type_percentage

    return (
        <LemonBanner type="warning" className="mt-4">
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="flex-1 min-w-[300px]">
                    <div className="font-semibold">Bot traffic may be skewing your split</div>
                    <p className="m-0">
                        Your exposure distribution doesn't match your rollout, and a large share of exposures look like
                        automated traffic:
                    </p>
                    <ul className="m-0 mt-1">
                        {missingUserAgent >= COMPOSITION_SHARE_DISPLAY_FLOOR && (
                            <li>
                                <strong>{missingUserAgent.toFixed(1)}%</strong> have no user agent
                            </li>
                        )}
                        {missingDeviceType >= COMPOSITION_SHARE_DISPLAY_FLOOR && (
                            <li>
                                <strong>{missingDeviceType.toFixed(1)}%</strong> have no device type
                            </li>
                        )}
                    </ul>
                    <p className="m-0 mt-1">
                        These are usually server-side, edge, or crawler requests, not real browser sessions. Because
                        bucketing hashes the distinct ID, a few shared or synthetic IDs can land in one variant and move
                        the whole split. Turn on{' '}
                        <Link to="https://posthog.com/docs/experiments/exposures" target="_blank">
                            exclude bot traffic
                        </Link>{' '}
                        to keep them out.
                    </p>
                </div>
                <div className="flex gap-2 items-center flex-shrink-0">
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() =>
                            openExposureCriteriaModal({
                                ...exposureCriteria,
                                exclude_bot_traffic: true,
                            })
                        }
                    >
                        Exclude bot traffic
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    )
}
