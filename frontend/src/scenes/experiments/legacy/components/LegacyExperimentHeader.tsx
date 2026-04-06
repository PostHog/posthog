import { DataCollection } from 'scenes/experiments/ExperimentView/DataCollection'

export function LegacyExperimentHeader(): JSX.Element {
    return (
        <>
            <div className="w-1/2 mt-8 xl:mt-0">
                <DataCollection />
            </div>
        </>
    )
}
