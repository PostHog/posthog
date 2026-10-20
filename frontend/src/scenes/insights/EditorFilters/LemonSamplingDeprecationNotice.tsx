import { LemonBanner } from '@posthog/lemon-ui'

import type { SamplingNoticeProps } from './SamplingDeprecationNotice'

export function LemonSamplingDeprecationNotice({
    samplingFactor,
    onDisableSampling,
}: SamplingNoticeProps): JSX.Element {
    return (
        <LemonBanner type="warning">
            <span>
                This insight currently uses {(samplingFactor * 100).toFixed(0)}% sampling. Sampling is being deprecated
                and will be removed in a future release.{' '}
                <button className="text-link font-semibold" onClick={onDisableSampling}>
                    Disable it now
                </button>{' '}
                and run on full data.
            </span>
        </LemonBanner>
    )
}
