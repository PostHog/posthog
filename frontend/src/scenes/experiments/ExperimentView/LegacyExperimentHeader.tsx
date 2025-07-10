import { DataCollection } from 'scenes/experiments/ExperimentView/DataCollection'

export function LegacyExperimentHeader(): JSX.Element {
    return (
        <>
            <div className="mt-8 w-1/2 xl:mt-0">
                <DataCollection />
            </div>
        </>
    )
}
