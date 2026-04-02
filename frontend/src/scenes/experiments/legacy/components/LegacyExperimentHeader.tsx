import { DataCollection } from 'scenes/experiments/ExperimentView/DataCollection'

/**
 * @deprecated
 * Legacy experiment header for ExperimentView.
 * Frozen copy for legacy experiments - do not modify.
 */
export function LegacyExperimentHeader(): JSX.Element {
    return (
        <>
            <div className="w-1/2 mt-8 xl:mt-0">
                <DataCollection />
            </div>
        </>
    )
}
