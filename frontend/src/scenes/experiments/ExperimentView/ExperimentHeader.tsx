import { IconCalculator } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { humanFriendlyNumber } from 'lib/utils'

import { experimentLogic } from '../experimentLogic'
import { RunningTimeCalculatorModal } from '../RunningTimeCalculator/RunningTimeCalculatorModal'
import { ExposureCriteria } from './ExposureCriteria'
import { PreLaunchChecklist } from './PreLaunchChecklist'

export function ExperimentHeader(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { openCalculateRunningTimeModal } = useActions(experimentLogic)

    return (
        <>
            <div className="w-1/2 mt-8 xl:mt-0">
                <div className="flex items-center gap-2 mb-1">
                    <h2 className="font-semibold text-lg m-0">Data collection</h2>
                    <LemonButton
                        icon={<IconCalculator />}
                        type="secondary"
                        size="xsmall"
                        onClick={openCalculateRunningTimeModal}
                        tooltip="Calculate running time"
                    />
                </div>
                <div>
                    <span className="card-secondary">Sample size:</span>{' '}
                    <span className="font-semibold">
                        {humanFriendlyNumber(experiment.parameters.recommended_sample_size || 0, 0)} persons
                    </span>
                </div>
                <div>
                    <span className="card-secondary">Running time:</span>{' '}
                    <span className="font-semibold">
                        {humanFriendlyNumber(experiment.parameters.recommended_running_time || 0, 0)}
                    </span>{' '}
                    days
                </div>
                <div className="mt-4">
                    <ExposureCriteria />
                </div>
            </div>
            <PreLaunchChecklist />
            <RunningTimeCalculatorModal />
        </>
    )
}
