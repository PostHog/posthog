import { RetentionLineGraph } from './RetentionLineGraph'
import { RetentionTable } from './RetentionTable'
import { LemonDivider } from '@posthog/lemon-ui'
import { RetentionModal } from './RetentionModal'
import { QueryContext } from '~/queries/types'
import { VizSpecificSettings } from '~/queries/schema'
import { InsightType } from '~/types'

export function RetentionContainer({
    inCardView,
    inSharedMode,
    vizSpecificSettings,
}: {
    inCardView?: boolean
    inSharedMode?: boolean
    context?: QueryContext
    vizSpecificSettings?: VizSpecificSettings[InsightType.RETENTION]
}): JSX.Element {
    const hideLineGraph = vizSpecificSettings?.hideLineGraph || inCardView
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
