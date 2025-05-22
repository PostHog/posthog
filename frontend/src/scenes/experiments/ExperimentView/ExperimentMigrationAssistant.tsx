import { IconOpenSidebar, IconRocket } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { ExperimentsHog } from 'lib/components/hedgehogs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import type { Experiment } from '~/types'

import { isLegacyExperiment } from '../utils'

type ExperimentMigrationAssistantProps = {
    experiment?: Experiment | null
    onClick: () => void
}

export const ExperimentMigrationAssistant = ({
    experiment,
    onClick,
}: ExperimentMigrationAssistantProps): JSX.Element | null => {
    /**
     * Bail if it's not a legacy experiment
     */
    if (experiment && !isLegacyExperiment(experiment)) {
        return null
    }

    return (
        <LemonBanner type="info" hideIcon={true} className="mb-5">
            <div className="flex gap-8 p-8 md:flex-row justify-center flex-wrap">
                <div className="flex justify-center items-center w-full md:w-50">
                    <ExperimentsHog className="w-full h-auto md:h-[200px] md:w-[200px] max-w-50" />
                </div>
                <div className="flex flex-col gap-2 flex-shrink max-w-180">
                    <h2 className="text-lg font-semibold">Migrate this experiment the new experimentation engine!</h2>
                    <ul className="list-disc list-inside font-normal">
                        <li>
                            <strong>Simple exposure configuration:</strong> Set a consistent exposure criteria for the
                            entire experiment.
                        </li>
                        <li>
                            <strong>Better metrics support:</strong> Improved support for conversion and time based
                            metrics.
                        </li>
                        <li>
                            <strong>Running time calculator:</strong> Use historical data to estimate your experiment
                            duration.
                        </li>
                        <li>
                            <strong>Better accuracy:</strong> Support outlier handling (Winsorization).
                        </li>
                    </ul>
                    <p className="font-normal">
                        Migrate this experiment to the new engine to unlock these (and future) features. We'll keep your
                        legacy experiment.
                    </p>
                    <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
                        <LemonButton className="hidden @md:flex" type="primary" icon={<IconRocket />} onClick={onClick}>
                            Migrate!
                        </LemonButton>
                        <LemonButton
                            type="tertiary"
                            sideIcon={<IconOpenSidebar className="w-4 h-4" />}
                            to="https://posthog.com/docs/experiments/new-experimentation-engine?utm_medium=in-product&utm_campaign=empty-state-docs-link"
                            data-attr="product-introduction-docs-link"
                            targetBlank
                        >
                            Learn more
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonBanner>
    )
}
