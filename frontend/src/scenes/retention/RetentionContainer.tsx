import { LemonDivider } from '@posthog/lemon-ui'

import { VizSpecificOptions } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import { InsightType } from '~/types'

import { RetentionLineGraph } from './RetentionLineGraph'
import { RetentionModal } from './RetentionModal'
import { RetentionTable } from './RetentionTable'

export function RetentionContainer({
    inCardView,
    inSharedMode,
    vizSpecificOptions,
}: {
    inCardView?: boolean
    inSharedMode?: boolean
    context?: QueryContext
    vizSpecificOptions?: VizSpecificOptions[InsightType.RETENTION]
}): JSX.Element {
    const hideLineGraph = vizSpecificOptions?.hideLineGraph || inCardView
    return (
        <div className="RetentionContainer">
            {hideLineGraph ? (
                <RetentionTable inCardView={inCardView} />
            ) : (
                <>
                    <div className="RetentionContainer__graph">
                        <RetentionLineGraph inSharedMode={inSharedMode} />
                    </div>
                    <LemonDivider />
                    <div className="RetentionContainer__table overflow-x-auto">
                        <RetentionTable inCardView={inCardView} />
                    </div>
                    <RetentionModal />
                </>
            )}
        </div>
    )
}
