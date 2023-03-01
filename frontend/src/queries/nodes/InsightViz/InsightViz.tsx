import { BindLogic, useValues } from 'kea'
import clsx from 'clsx'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { isFunnelsQuery } from '~/queries/utils'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { InsightQueryNode, InsightVizNode } from '../../schema'

import { InsightContainer } from './InsightContainer'
import { EditorFilters } from './EditorFilters'
import { InsightLogicProps, ItemMode } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

/** The key for the dataNodeLogic mounted by an InsightViz for insight of insightProps */
export const insightVizDataNodeKey = (insightProps: InsightLogicProps): string => {
    return `InsightViz.${keyForInsightLogicProps('new')(insightProps)}`
}

type InsightVizProps = {
    query: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
}

export function InsightViz({ query, setQuery }: InsightVizProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const dataNodeLogicProps: DataNodeLogicProps = { query: query.source, key: insightVizDataNodeKey(insightProps) }

    const { insightMode } = useValues(insightSceneLogic)

    const isFunnels = isFunnelsQuery(query.source)

    const setQuerySource = (source: InsightQueryNode): void => {
        setQuery?.({ ...query, source })
    }

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <div
                className={clsx('insight-wrapper', {
                    'insight-wrapper--singlecolumn': isFunnels,
                })}
            >
                <EditorFilters query={query.source} setQuery={setQuerySource} showing={insightMode === ItemMode.Edit} />

                <div className="insights-container" data-attr="insight-view">
                    <InsightContainer insightMode={insightMode} />
                </div>
            </div>
        </BindLogic>
    )
}
