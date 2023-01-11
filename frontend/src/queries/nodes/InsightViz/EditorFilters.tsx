import { CSSTransition } from 'react-transition-group'
import clsx from 'clsx'
import { useValues } from 'kea'

import { QueryInsightEditorFilterGroup, QueryInsightEditorFilter, QueryEditorFilterProps } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

import {
    isTrendsQuery,
    isFunnelsQuery,
    isRetentionQuery,
    isPathsQuery,
    isStickinessQuery,
    isLifecycleQuery,
} from '~/queries/utils'
import { InsightQueryNode } from '~/queries/schema'
import { EditorFilterGroup } from './EditorFilterGroup'
import { LifecycleGlobalFilters } from './LifecycleGlobalFilters'
import { LifecycleToggles } from './LifecycleToggles'
import { TrendsSeries } from './TrendsSeries'

export interface EditorFiltersProps {
    query: InsightQueryNode
    setQuery: (node: InsightQueryNode) => void
}

export function EditorFilters({ query, setQuery }: EditorFiltersProps): JSX.Element {
    const showFilters = true // TODO: implement with insightVizLogic

    const isTrends = isTrendsQuery(query)
    const isFunnels = isFunnelsQuery(query)
    const isRetention = isRetentionQuery(query)
    const isPaths = isPathsQuery(query)
    const isStickiness = isStickinessQuery(query)
    const isLifecycle = isLifecycleQuery(query)

    const isTrendsLike = isTrends || isLifecycle || isStickiness
    const hasPropertyFilters = isTrends || isStickiness || isRetention || isPaths || isFunnels

    const { insight, insightProps, filterPropertiesCount } = useValues(insightLogic)

    const editorFilters: QueryInsightEditorFilterGroup[] = [
        {
            title: 'Series',
            editorFilters: filterFalsy([
                isTrendsLike && {
                    key: 'series',
                    // label: isTrends ? TrendsSeriesLabel : undefined,
                    component: TrendsSeries,
                },
                // isTrends
                //     ? {
                //           key: 'formula',
                //           label: TrendsFormulaLabel,
                //           component: TrendsFormula,
                //       }
                //     : null,
            ]),
        },
        {
            title: 'Filters',
            count: filterPropertiesCount,
            editorFilters: filterFalsy([
                isLifecycle
                    ? {
                          key: 'properties',
                          label: 'Filters',
                          position: 'right',
                          component: LifecycleGlobalFilters as (props: QueryEditorFilterProps) => JSX.Element | null,
                      }
                    : null,
                isLifecycle
                    ? {
                          key: 'toggles',
                          label: 'Lifecycle Toggles',
                          position: 'right',
                          component: LifecycleToggles as (props: QueryEditorFilterProps) => JSX.Element | null,
                      }
                    : null,
                hasPropertyFilters
                    ? {
                          key: 'properties',
                          label: 'Filters',
                          position: 'right',
                          //   component: GlobalAndOrFilters,
                          component: () => <div>GlobalAndOrFilters</div>,
                      }
                    : null,
            ]),
        },
    ]

    return (
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
                            query={query}
                            setQuery={setQuery}
                        />
                    ))}
                </div>
            </div>
        </CSSTransition>
    )
}

function filterFalsy(a: (QueryInsightEditorFilter | false | null | undefined)[]): QueryInsightEditorFilter[] {
    return a.filter((e) => !!e) as QueryInsightEditorFilter[]
}
