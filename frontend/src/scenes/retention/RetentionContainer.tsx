import { useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { InsightVizNode, VizSpecificOptions } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { InsightType, RetentionDashboardDisplayType } from '~/types'

import { RetentionGraph } from './RetentionGraph'
import { RetentionModal } from './RetentionModal'
import { RetentionTable } from './RetentionTable'
import { retentionLogic } from './retentionLogic'

export function RetentionContainer({
    inCardView,
    embedded,
    inSharedMode,
    vizSpecificOptions,
}: {
    inCardView?: boolean
    embedded?: boolean
    inSharedMode?: boolean
    context?: QueryContext<InsightVizNode>
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
                    <RetentionTable inSharedMode={inSharedMode} embedded={embedded} />
                </div>
            )}
            {!inSharedMode ? <RetentionModal /> : null}
        </div>
    )
}
