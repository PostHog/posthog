import { useState } from 'react'
import { CSSTransition } from 'react-transition-group'
import { useValues } from 'kea'
import clsx from 'clsx'

import { InsightEditorFilterGroup, InsightEditorFilter } from '~/types'
import { EditorFilterGroup } from 'scenes/insights/EditorFilters/EditorFilterGroup'
import { insightLogic } from 'scenes/insights/insightLogic'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { InsightVizNode } from '../../schema'

import { LifecycleGlobalFilters } from './LifecycleGlobalFilters'

type InsightVizProps = {
    query: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
}

let uniqueNode = 0

export function InsightViz({ query }: InsightVizProps): JSX.Element {
    const [key] = useState(() => `InsightViz.${uniqueNode++}`)

    const dataNodeLogicProps: DataNodeLogicProps = { query: query.source, key }
    const {
        response,
        responseLoading,
        // canLoadNextData,
        // canLoadNewData,
        // nextDataLoading,
        // newDataLoading,
    } = useValues(dataNodeLogic(dataNodeLogicProps))

    const { insight, insightProps, filterPropertiesCount } = useValues(insightLogic)

    const isFunnels = false // TODO: implement with funnel queries
    const isLifecycle = true
    const showFilters = true // TODO: implement with insightVizLogic

    const editorFilters: InsightEditorFilterGroup[] = [
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

    return (
        <>
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
                            />
                        ))}
                    </div>
                </div>
            </CSSTransition>
            <div>
                <h3>InsightViz</h3>
                <h4>Query</h4>
                <pre>{JSON.stringify(query, null, 2)}</pre>
                <h4>Response</h4>
                {responseLoading ? <span>Loading...</span> : <pre>{JSON.stringify(response, null, 2)}</pre>}
            </div>
        </>
    )
}

function filterFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e) => !!e) as InsightEditorFilter[]
}
