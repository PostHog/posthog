import '../Experiment.scss'

import { useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { capitalizeFirstLetter } from 'lib/utils'

import { InsightType } from '~/types'

import { experimentLogic } from '../experimentLogic'

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
            const secondBestVariant = sortedConversionRates[1]
            const difference = winningVariant.conversionRate - secondBestVariant.conversionRate

            return (
                <div className="items-center inline-flex">
                    <div
                        className="w-2 h-2 rounded-full mr-1"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ backgroundColor: getSeriesColor(winningVariant.index + 1) }}
                    />
                    <span className="font-semibold">{capitalizeFirstLetter(winningVariant.key)}</span>
                    <span>&nbsp;is winning with a conversion rate&nbsp;</span>
                    <span className="font-semibold text-success items-center">
                        increase of {`${difference.toFixed(2)}%`}
                    </span>
                    <span>&nbsp;percentage points (vs&nbsp;</span>
                    <div
                        className="w-2 h-2 rounded-full mr-1"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            backgroundColor: getSeriesColor(secondBestVariant.index + 1),
                        }}
                    />
                    <span className="font-semibold">{capitalizeFirstLetter(secondBestVariant.key)}</span>
                    <span>).&nbsp;</span>
                </div>
            )
        }

        const highestProbabilityVariant = getHighestProbabilityVariant(experimentResults)
        const index = getIndexForVariant(experimentResults, highestProbabilityVariant || '')
        if (highestProbabilityVariant && index !== null && experimentResults) {
            const { probability } = experimentResults

            return (
                <div className="items-center inline-flex">
                    <div
                        className="w-2 h-2 rounded-full mr-1"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            backgroundColor: getSeriesColor(index + 2),
                        }}
                    />
                    <span className="font-semibold">{capitalizeFirstLetter(highestProbabilityVariant)}</span>
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
            <>
                <span>Your results are&nbsp;</span>
                <span className="font-semibold">{`${areResultsSignificant ? 'significant' : 'not significant'}`}.</span>
            </>
        )
    }

    return (
        <div>
            <h2 className="font-semibold text-lg">Summary</h2>
            <div className="items-center inline-flex">
                <WinningVariantText />
                <SignificanceText />
            </div>
        </div>
    )
}
