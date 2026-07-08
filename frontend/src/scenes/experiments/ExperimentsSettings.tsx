import { useValues } from 'kea'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { MAX_LOOKBACK_DAYS, MIN_LOOKBACK_DAYS } from 'scenes/experiments/constants'
import { DefaultCupedEnabled } from 'scenes/settings/environment/DefaultCupedEnabled'
import { DefaultCupedLookbackDays } from 'scenes/settings/environment/DefaultCupedLookbackDays'
import { DefaultExperimentConfidenceLevel } from 'scenes/settings/environment/DefaultExperimentConfidenceLevel'
import { DefaultExperimentStatsMethod } from 'scenes/settings/environment/DefaultExperimentStatsMethod'
import { DefaultOnlyCountMaturedUsers } from 'scenes/settings/environment/DefaultOnlyCountMaturedUsers'
import { DefaultSequentialTestingEnabled } from 'scenes/settings/environment/DefaultSequentialTestingEnabled'
import { DefaultSequentialTuningParameter } from 'scenes/settings/environment/DefaultSequentialTuningParameter'
import { ExperimentRecalculationTime } from 'scenes/settings/environment/ExperimentRecalculationTime'
import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'

import { DefaultMinimumDetectableEffect } from './DefaultMinimumDetectableEffect'

/**
 * although this works fine for now, if we keep adding more settings we need to refactor this to use the
 * <Settings /> component. That will require we create a new section for experiments on the SettingsMap.
 */
export function ExperimentsSettings(): JSX.Element {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)

    if (experimentsConfigLoading && !experimentsConfig) {
        return <SpinnerOverlay sceneLevel />
    }

    return (
        <div className="space-y-8">
            <div>
                <LemonLabel className="text-base">Default statistical method</LemonLabel>
                <p className="text-secondary mt-2">
                    Choose the default statistical method for experiment analysis. This setting applies to all new
                    experiments in this environment and can be overridden per experiment.
                </p>
                <DefaultExperimentStatsMethod />
            </div>
            <div>
                <LemonLabel className="text-base">Default confidence level</LemonLabel>
                <p className="text-secondary mt-2">
                    Higher confidence level reduces false positives but requires more data. Can be overridden per
                    experiment.
                </p>
                <DefaultExperimentConfidenceLevel />
            </div>
            <div>
                <LemonLabel className="text-base">Default minimum detectable effect</LemonLabel>
                <p className="text-secondary mt-2">
                    The smallest effect size you want to detect with statistical significance. Lower values require more
                    data and longer run times. Can be overridden per experiment.
                </p>
                <DefaultMinimumDetectableEffect />
            </div>
            <div>
                <LemonLabel className="text-base">Daily recalculation time</LemonLabel>
                <p className="text-secondary mt-2">
                    Select the time of day when experiment metrics should be recalculated. This time is in your
                    project's timezone.
                </p>
                <ExperimentRecalculationTime />
            </div>
            <div>
                <LemonLabel className="text-base">Default conversion window filter</LemonLabel>
                <p className="text-secondary mt-2">
                    When enabled, new experiments exclude participants whose conversion or retention window hasn't
                    elapsed yet. Can be overridden per experiment.
                </p>
                <DefaultOnlyCountMaturedUsers />
            </div>
            <div>
                <LemonLabel className="text-base">Default CUPED variance reduction</LemonLabel>
                <p className="text-secondary mt-2">
                    When enabled, experiments will use CUPED variance reduction. CUPED uses pre-experiment data to
                    detect significant effects faster on supported metrics. Can be overridden per experiment.
                </p>
                <DefaultCupedEnabled />
            </div>
            <div>
                <LemonLabel className="text-base">Default CUPED lookback window</LemonLabel>
                <p className="text-secondary mt-2">
                    Number of days before the experiment start to use as the pre-experiment window. Must be between{' '}
                    {MIN_LOOKBACK_DAYS} and {MAX_LOOKBACK_DAYS} days. Can be overridden per experiment.
                </p>
                <DefaultCupedLookbackDays />
            </div>
            <div>
                <LemonLabel className="text-base">Default sequential testing</LemonLabel>
                <p className="text-secondary mt-2">
                    When enabled, frequentist experiments will use sequential testing by default, producing always-valid
                    p-values that are robust to peeking. Confidence intervals are wider in exchange. Only applies to the
                    frequentist statistical method. Can be overridden per experiment.
                </p>
                <DefaultSequentialTestingEnabled />
            </div>
            <div>
                <LemonLabel className="text-base">Default sequential testing tuning parameter</LemonLabel>
                <p className="text-secondary mt-2">
                    Roughly the sample size at which the always-valid confidence sequence is tightest. Set close to the
                    expected total sample size of new experiments to minimize the width penalty. Can be overridden per
                    experiment.
                </p>
                <DefaultSequentialTuningParameter />
            </div>
        </div>
    )
}
