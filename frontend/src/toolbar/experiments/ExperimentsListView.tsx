import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

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
        <div key="experiments-list" className="overflow-y-scoll deprecated-space-y-px flex h-full flex-col">
            {experiments.length ? (
                experiments.map((experiment, index) => (
                    <Link
                        subtle
                        key={experiment.id}
                        onClick={() => selectExperiment(experiment.id || null)}
                        className="my-1 w-full font-medium"
                    >
                        <span key={experiment.id + 'index'} className="inline-block min-w-[2rem] text-left">
                            {index + 1}.
                        </span>
                        <span key={experiment.id + 'name'} className="flex-grow">
                            {experiment.name || <span className="text-secondary italic">Untitled</span>}
                        </span>
                    </Link>
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
