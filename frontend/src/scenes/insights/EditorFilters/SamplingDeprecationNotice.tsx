import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { InsightLogicProps } from '~/types'

import { LemonSamplingDeprecationNotice } from './LemonSamplingDeprecationNotice'
import { QuillSamplingDeprecationNotice } from './QuillSamplingDeprecationNotice'

interface SamplingDeprecationNoticeProps {
    insightProps: InsightLogicProps
}

export interface SamplingNoticeProps {
    samplingFactor: number
    onDisableSampling: () => void
}

export function SamplingDeprecationNotice({ insightProps }: SamplingDeprecationNoticeProps): JSX.Element | null {
    const { samplingFactor } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')

    const hasSampling = samplingFactor != null && samplingFactor < 1

    if (!hasSampling) {
        return null
    }

    const props: SamplingNoticeProps = {
        samplingFactor,
        onDisableSampling: () => {
            updateQuerySource({ samplingFactor: null })
        },
    }
    return quillEnabled ? <QuillSamplingDeprecationNotice {...props} /> : <LemonSamplingDeprecationNotice {...props} />
}
