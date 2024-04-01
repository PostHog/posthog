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
        getHighestProbabilityVariant,
        areResultsSignificant,
        conversionRateForVariant,
    } = useValues(experimentLogic)

    function WinningVariantText(): JSX.Element {
        const winningVariant = getHighestProbabilityVariant(experimentResults)

        if (experimentInsightType === InsightType.FUNNELS) {
            const winningConversionRate = conversionRateForVariant(experimentResults, winningVariant || '')
            const controlConversionRate = conversionRateForVariant(experimentResults, 'control')
            const difference = parseFloat(winningConversionRate) - parseFloat(controlConversionRate)

            if (difference === 0) {
                return (
                    <span>
                        <b>No variant is winning</b> at this moment.&nbsp;
                    </span>
                )
            }

            return (
                <div className="items-center inline-flex flex-wrap">
                    <VariantTag variantKey={winningVariant || ''} />
                    <span>&nbsp;is winning with a conversion rate&nbsp;</span>
                    <span className="font-semibold text-success items-center">
                        increase of {`${difference.toFixed(2)}%`}
                    </span>
                    <span>&nbsp;percentage points (vs&nbsp;</span>
                    <VariantTag variantKey="control" />
                    <span>).&nbsp;</span>
                </div>
            )
        }

        const index = getIndexForVariant(experimentResults, winningVariant || '')
        if (winningVariant && index !== null && experimentResults) {
            const { probability } = experimentResults

            return (
                <div className="items-center inline-flex flex-wrap">
                    <VariantTag variantKey={winningVariant} />
                    <span>&nbsp;is winning with a&nbsp;</span>
                    <span className="font-semibold text-success items-center">
                        {`${(probability[winningVariant] * 100).toFixed(2)}% probability`}&nbsp;
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
