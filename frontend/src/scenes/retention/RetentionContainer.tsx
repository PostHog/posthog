import { LemonDivider } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

import { VizSpecificOptions } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { InsightType, RetentionDashboardDisplayType } from '~/types'

import { RetentionGraph } from './RetentionGraph'
import { retentionLogic } from './retentionLogic'
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
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(retentionLogic(insightProps))

    const showLineGraph =
        !vizSpecificOptions?.hideLineGraph &&
        (!inCardView ||
            (!!retentionFilter?.dashboardDisplay && // for backwards compatibility as we were hiding the graph on dashboards before adding this property
                retentionFilter?.dashboardDisplay !== RetentionDashboardDisplayType.TableOnly))

    const showTable = !inCardView || retentionFilter?.dashboardDisplay !== RetentionDashboardDisplayType.GraphOnly

    return (
        <div className="RetentionContainer">
            {showLineGraph && (
                <div className="RetentionContainer__graph">
                    <RetentionGraph inSharedMode={inSharedMode} />
                </div>
            )}
            {showLineGraph && showTable ? <LemonDivider /> : null}
            {showTable && (
                <div className="RetentionContainer__table overflow-x-auto">
                    <RetentionTable inSharedMode={inSharedMode} />
                </div>
            )}
            {!inSharedMode ? <RetentionModal /> : null}
        </div>
    )
}
