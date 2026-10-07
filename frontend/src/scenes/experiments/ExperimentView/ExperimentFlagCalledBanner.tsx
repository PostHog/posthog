import { useValues } from 'kea'

import { experimentFlagCalledReferences } from 'lib/components/FlagCalledRebuildBanner/flagCalledDependencies'
import { FlagCalledRebuildBanner } from 'lib/components/FlagCalledRebuildBanner/FlagCalledRebuildBanner'

import { experimentLogic } from '../experimentLogic'

export function ExperimentFlagCalledBanner(): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    return (
        <FlagCalledRebuildBanner
            artifactType="experiment"
            references={experimentFlagCalledReferences(experiment)}
            className="mb-4"
        >
            This experiment counts exposures on Feature flag called, and it won't count new exposures once your
            organization's flag calls move out of the events table. Reach a decision before then, or launch a new
            experiment, which counts exposures on Experiment exposure.
        </FlagCalledRebuildBanner>
    )
}
