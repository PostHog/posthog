import { BindLogic, useValues } from 'kea'
import clsx from 'clsx'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { isFunnelsQuery } from '~/queries/utils'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { InsightQueryNode, InsightVizNode, QueryContext } from '../../schema'

import { InsightContainer } from './InsightContainer'
import { EditorFilters } from './EditorFilters'
import { InsightLogicProps, ItemMode } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getCachedResults } from './utils'
import { useState } from 'react'

import './Insight.scss'

/** The key for the dataNodeLogic mounted by an InsightViz for insight of insightProps */
export const insightVizDataNodeKey = (insightProps: InsightLogicProps): string => {
    return `InsightViz.${keyForInsightLogicProps('new')(insightProps)}`
}

type InsightVizProps = {
    query: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
    context?: QueryContext
    readOnly?: boolean
}

let uniqueNode = 0

export function InsightViz({ query, setQuery, context, readOnly }: InsightVizProps): JSX.Element {
    const [key] = useState(() => `InsightViz.${uniqueNode++}`)
    const insightProps: InsightLogicProps = context?.insightProps || { dashboardItemId: `new-AdHoc.${key}`, query }
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(insightProps.cachedInsight, query.source),
        doNotLoad: insightProps.doNotLoad,
    }

    const { insightMode } = useValues(insightSceneLogic)

    const isFunnels = isFunnelsQuery(query.source)

    const setQuerySource = (source: InsightQueryNode): void => {
        setQuery?.({ ...query, source })
    }

    const showIfFull = !!query.full
    const disableHeader = query.showHeader ? !query.showHeader : !showIfFull
    const disableTable = query.showTable ? !query.showTable : !showIfFull
    const disableCorrelationTable = query.showCorrelationTable ? !query.showCorrelationTable : !showIfFull
    const disableLastComputation = query.showLastComputation ? !query.showLastComputation : !showIfFull
    const disableLastComputationRefresh = query.showLastComputationRefresh
        ? !query.showLastComputationRefresh
        : !showIfFull

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <div
                    className={clsx('insight-wrapper', {
                        'insight-wrapper--singlecolumn': isFunnels,
                    })}
                >
                    {!readOnly && (
                        <EditorFilters
                            query={query.source}
                            setQuery={setQuerySource}
                            showing={insightMode === ItemMode.Edit}
                        />
                    )}

                    <div className="insights-container" data-attr="insight-view">
                        <InsightContainer
                            insightMode={insightMode}
                            context={context}
                            disableHeader={disableHeader}
                            disableTable={disableTable}
                            disableCorrelationTable={disableCorrelationTable}
                            disableLastComputation={disableLastComputation}
                            disableLastComputationRefresh={disableLastComputationRefresh}
                        />
                    </div>
                </div>
            </BindLogic>
        </BindLogic>
    )
}
