import '../Experiment.scss'

import { useValues } from 'kea'

import { InsightType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'

export function Overview(): JSX.Element {
    const {
        experimentResults,
        getIndexForVariant,
        experimentInsightType,
        sortedConversionRates,
        getHighestProbabilityVariant,
        areResultsSignificant,
    } = useValues(experimentLogic)

    function WinningVariantText(): JSX.Element {
        if (experimentInsightType === InsightType.FUNNELS) {
            const winningVariant = sortedConversionRates[0]

            let comparisonVariant
            if (winningVariant.key === 'control') {
                comparisonVariant = sortedConversionRates[1]
            } else {
                comparisonVariant = sortedConversionRates.find(({ key }) => key === 'control')
            }

            if (!comparisonVariant) {
                return <></>
            }

            const difference = winningVariant.conversionRate - comparisonVariant.conversionRate
            if (winningVariant.conversionRate === comparisonVariant.conversionRate) {
                return (
                    <span>
                        <b>No variant is winning</b> at this moment.&nbsp;
                    </span>
                )
            }

            return (
                <div className="items-center inline-flex flex-wrap">
                    <VariantTag variantKey={winningVariant.key} />
                    <span>&nbsp;is winning with a conversion rate&nbsp;</span>
                    <span className="font-semibold text-success items-center">
                        increase of {`${difference.toFixed(2)}%`}
                    </span>
                    <span>&nbsp;percentage points (vs&nbsp;</span>
                    <VariantTag variantKey={comparisonVariant.key} />
                    <span>).&nbsp;</span>
                </div>
            )
        }

        const highestProbabilityVariant = getHighestProbabilityVariant(experimentResults)
        const index = getIndexForVariant(experimentResults, highestProbabilityVariant || '')
        if (highestProbabilityVariant && index !== null && experimentResults) {
            const { probability } = experimentResults

            return (
                <div className="items-center inline-flex flex-wrap">
                    <VariantTag variantKey={highestProbabilityVariant} />
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
