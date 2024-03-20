import '../Experiment.scss'

import { Empty } from 'antd'
import { useValues } from 'kea'

import { experimentLogic } from '../experimentLogic'

export function NoResultsEmptyState(): JSX.Element {
    const { experimentResultsLoading, experimentResultCalculationError } = useValues(experimentLogic)

    if (experimentResultsLoading) {
        return <></>
    }

    return (
        <div>
            <h2 className="font-semibold text-lg">Results</h2>
            <div className="border rounded bg-bg-light pt-6 pb-8 text-muted">
                <div className="flex flex-col items-center mx-auto">
                    <Empty className="my-4" image={Empty.PRESENTED_IMAGE_SIMPLE} description="" />
                    <h2 className="text-xl font-semibold leading-tight">There are no experiment results yet</h2>
                    {!!experimentResultCalculationError && (
                        <div className="text-sm text-center text-balance">{experimentResultCalculationError}</div>
                    )}
                    <div className="text-sm text-center text-balance">
                        Wait a bit longer for your users to be exposed to the experiment. Double check your feature flag
                        implementation if you're still not seeing results.
                    </div>
                </div>
            </div>
        </div>
    )
}
