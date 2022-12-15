import { useEffect, useState } from 'react'
import { CSSTransition } from 'react-transition-group'
import { BindLogic, useActions, useValues } from 'kea'
import clsx from 'clsx'

import { QueryInsightEditorFilterGroup, QueryInsightEditorFilter } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { InsightQueryNode, InsightVizNode } from '../../schema'

import { EditorFilterGroup } from './EditorFilterGroup'
import { LifecycleGlobalFilters } from './LifecycleGlobalFilters'
import { queryNodeToFilter } from '../InsightQuery/queryNodeToFilter'

type InsightVizProps = {
    query: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
}

let uniqueNode = 0

export function InsightViz({ query, setQuery }: InsightVizProps): JSX.Element {
    const [key] = useState(() => `InsightViz.${uniqueNode++}`)

    const dataNodeLogicProps: DataNodeLogicProps = { query: query.source, key }
    const {
        response,
        // responseLoading,
        // canLoadNextData,
        // canLoadNewData,
        // nextDataLoading,
        // newDataLoading,
    } = useValues(dataNodeLogic(dataNodeLogicProps))

    const { insight, insightProps, filterPropertiesCount } = useValues(insightLogic)
    const { setInsight } = useActions(insightLogic)

    // TODO: use connected logic instead of useEffect?
    useEffect(() => {
        if (response) {
            setInsight(
                {
                    ...insight,
                    result: response.result,
                    next: response.next,
                    timezone: response.timezone,
                    filters: queryNodeToFilter(query.source),
                },
                {}
            )
        }
    }, [response])

    const isFunnels = false // TODO: implement with funnel queries
    const isLifecycle = true
    const showFilters = true // TODO: implement with insightVizLogic

    const editorFilters: QueryInsightEditorFilterGroup[] = [
        {
            title: 'Filters',
            count: filterPropertiesCount,
            editorFilters: filterFalsy([
                isLifecycle
                    ? {
                          key: 'properties',
                          label: 'Filters',
                          position: 'right',
                          component: LifecycleGlobalFilters,
                      }
                    : null,
                // isLifecycle
                //     ? {
                //           key: 'toggles',
                //           label: 'Lifecycle Toggles',
                //           position: 'right',
                //           component: LifecycleToggles,
                //       }
                //     : null,
            ]),
        },
    ]

    const setQuerySource = (source: InsightQueryNode): void => {
        setQuery?.({ ...query, source })
    }

    return (
        <>
            {/* <BindLogic logic={dataTableLogic} props={dataTableLogicProps}> */}
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <CSSTransition in={showFilters} timeout={250} classNames="anim-" mountOnEnter unmountOnExit>
                    <div
                        className={clsx('EditorFiltersWrapper', {
                            'EditorFiltersWrapper--singlecolumn': isFunnels,
                        })}
                    >
                        <div className="EditorFilters">
                            {editorFilters.map((editorFilterGroup) => (
                                <EditorFilterGroup
                                    key={editorFilterGroup.title}
                                    editorFilterGroup={editorFilterGroup}
                                    insight={insight}
                                    insightProps={insightProps}
                                    query={query.source}
                                    setQuery={setQuerySource}
                                />
                            ))}
                        </div>
                    </div>
                </CSSTransition>
            </BindLogic>
            {/* </BindLogic> */}
            <div>
                <h4>Query</h4>
                <pre>{JSON.stringify(query, null, 2)}</pre>
            </div>
        </>
    )
}

function filterFalsy(a: (QueryInsightEditorFilter | false | null | undefined)[]): QueryInsightEditorFilter[] {
    return a.filter((e) => !!e) as QueryInsightEditorFilter[]
}
