import { LemonTagType } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils/strings'

import type { TraceSentimentApi, TraceSentimentLabelEnumApi } from '../../../generated/api.schemas'
import type { TraceCellStatus } from '../../shared/cellLoads'
import { ChipTag } from '../../trace/components/ChipTag'
import { TraceCellValue } from './TraceCellValue'

const TAG_TYPE: Record<TraceSentimentLabelEnumApi, LemonTagType> = {
    positive: 'success',
    neutral: 'muted',
    negative: 'danger',
}

export interface TraceSentimentCellProps {
    sentiment: TraceSentimentApi | null
    status: TraceCellStatus
}

export function TraceSentimentCell({ sentiment, status }: TraceSentimentCellProps): JSX.Element {
    return (
        <TraceCellValue status={status} skeletonWidth="w-20">
            {sentiment === null ? null : (
                <ChipTag type={TAG_TYPE[sentiment.label]} size="small" className="whitespace-nowrap">
                    {`${capitalizeFirstLetter(sentiment.label)} ${Math.round(sentiment.score * 100)}%`}
                </ChipTag>
            )}
        </TraceCellValue>
    )
}
