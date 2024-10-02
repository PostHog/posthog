import { Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { experimentsLogic } from '~/toolbar/experiments/experimentsLogic'
import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'
import { Experiment } from '~/types'

interface ExperimentsListViewProps {
    experiments: Experiment[]
}

export function ExperimentsListView({ experiments }: ExperimentsListViewProps): JSX.Element {
    const { allExperimentsLoading, searchTerm } = useValues(experimentsLogic)
    const { selectExperiment } = useActions(experimentsTabLogic)

    return (
        <div className="flex flex-col h-full overflow-y-scoll space-y-px">
            {experiments.length ? (
                experiments.map((experiment, index) => (
                    <>
                        <Link
                            subtle
                            key={experiment.id}
                            onClick={() => selectExperiment(experiment.id || null)}
                            className="font-medium my-1 w-full"
                        >
                            <span className="min-w-[2rem] inline-block text-left">{index + 1}.</span>
                            <span className="flex-grow">
                                {experiment.name || <span className="italic text-muted-alt">Untitled</span>}
                            </span>
                        </Link>
                    </>
                ))
            ) : allExperimentsLoading ? (
                <div className="flex items-center">
                    <Spinner className="text-4xl" />
                </div>
            ) : (
                <div className="p-2">No {searchTerm.length ? 'matching ' : ''}experiments found.</div>
            )}
        </div>
    )
}
