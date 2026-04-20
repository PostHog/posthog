import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { InsightLogicProps } from '~/types'

interface SamplingDeprecationNoticeProps {
    insightProps: InsightLogicProps
}

export function SamplingDeprecationNotice({ insightProps }: SamplingDeprecationNoticeProps): JSX.Element | null {
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    const hasSampling = querySource?.samplingFactor != null && querySource.samplingFactor < 1

    if (!hasSampling) {
        return null
    }

    return (
        <LemonBanner type="warning">
            <span>
                This insight currently uses {(querySource.samplingFactor! * 100).toFixed(0)}% sampling. Sampling is
                being deprecated and will be removed in a future release.{' '}
                <button
                    className="text-link font-semibold"
                    onClick={() => {
                        updateQuerySource({ samplingFactor: null })
                    }}
                >
                    Disable it now
                </button>{' '}
                and run on full data.
            </span>
        </LemonBanner>
    )
}
