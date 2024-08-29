import '../Experiment.scss'

import { useValues } from 'kea'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'

export function Overview(): JSX.Element {
    const { experimentId, experimentResults, getIndexForVariant, getHighestProbabilityVariant, areResultsSignificant } =
        useValues(experimentLogic)

    function WinningVariantText(): JSX.Element {
        const highestProbabilityVariant = getHighestProbabilityVariant(experimentResults)
        const index = getIndexForVariant(experimentResults, highestProbabilityVariant || '')
        if (highestProbabilityVariant && index !== null && experimentResults) {
            const { probability } = experimentResults

            return (
                <div className="items-center inline-flex flex-wrap">
                    <VariantTag experimentId={experimentId} variantKey={highestProbabilityVariant} />
                    <span>&nbsp;is winning with a&nbsp;</span>
                    <span className="font-semibold text-success items-center">
                        {`${(probability[highestProbabilityVariant] * 100).toFixed(2)}% probability`}&nbsp;
                    </span>
                    <span>of being best.&nbsp;</span>
                </div>
            )
        }

        return <></>
    }

    function SignificanceText(): JSX.Element {
        return (
            <div className="flex-wrap">
                <span>Your results are&nbsp;</span>
                <span className="font-semibold">{`${areResultsSignificant ? 'significant' : 'not significant'}`}.</span>
            </div>
        )
    }

    return (
        <div>
            <h2 className="font-semibold text-lg">Summary</h2>
            <div className="items-center inline-flex flex-wrap">
                <WinningVariantText />
                <SignificanceText />
            </div>
        </div>
    )
}
