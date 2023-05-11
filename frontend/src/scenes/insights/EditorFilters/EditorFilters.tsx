import { InsightEditorFilter, InsightEditorFilterGroup, InsightLogicProps } from '~/types'
import { CSSTransition } from 'react-transition-group'

import { PathsAdvanced } from './PathsAdvanced'
import { FunnelsAdvanced } from './FunnelsAdvanced'
import { PathsExclusions } from './PathsExclusions'
import { EditorFilterGroup } from './EditorFilterGroup'
import { useValues } from 'kea'
import { insightLogic } from '../insightLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import clsx from 'clsx'
import { isFunnelsFilter, isPathsFilter, isTrendsFilter } from 'scenes/insights/sharedUtils'

export interface EditorFiltersProps {
    insightProps: InsightLogicProps
    showing: boolean
}

export function EditorFilters({ insightProps, showing }: EditorFiltersProps): JSX.Element {
    const logic = insightLogic(insightProps)
    const { filters, insight } = useValues(logic)

    const { advancedOptionsUsedCount } = useValues(funnelLogic(insightProps))

    const isTrends = isTrendsFilter(filters)
    const isPaths = isPathsFilter(filters)
    const isFunnels = isFunnelsFilter(filters)

    const advancedOptionsCount = advancedOptionsUsedCount + (isTrends && filters.formula ? 1 : 0)
    const advancedOptionsExpanded = !!advancedOptionsCount

    const editorFilters: InsightEditorFilterGroup[] = [
        {
            title: 'Exclusions',
            position: 'right',
            editorFilters: filterFalsy([
                isPaths && {
                    key: 'paths-exclusions',
                    label: 'Exclusions',
                    position: 'right',
                    tooltip: (
                        <>Exclude events from Paths visualisation. You can use wildcard groups in exclusions as well.</>
                    ),
                    component: PathsExclusions,
                },
            ]),
        },
        {
            title: 'Advanced Options',
            position: 'left',
            defaultExpanded: advancedOptionsExpanded,
            count: advancedOptionsCount,
            editorFilters: filterFalsy([
                isPaths && {
                    key: 'paths-advanced',
                    component: PathsAdvanced,
                },
                isFunnels && {
                    key: 'funnels-advanced',
                    component: FunnelsAdvanced,
                },
            ]),
        },
    ].filter((x) => x.editorFilters.length > 0)

    const leftFilters = editorFilters.reduce(
        (acc, x) => acc.concat(x.editorFilters.filter((y) => y.position !== 'right')),
        [] as InsightEditorFilter[]
    )
    const rightFilters = editorFilters.reduce(
        (acc, x) => acc.concat(x.editorFilters.filter((y) => y.position === 'right')),
        [] as InsightEditorFilter[]
    )

    const legacyEditorFilterGroups: InsightEditorFilterGroup[] = [
        {
            title: 'Left',
            editorFilters: leftFilters,
        },
        {
            title: 'right',
            editorFilters: rightFilters,
        },
    ]

    return (
        <CSSTransition in={showing} timeout={250} classNames="anim-" mountOnEnter unmountOnExit>
            <div
                className={clsx('EditorFiltersWrapper', {
                    'EditorFiltersWrapper--singlecolumn': isFunnels,
                })}
            >
                <div className="EditorFilters">
                    {(isFunnels ? editorFilters : legacyEditorFilterGroups).map((editorFilterGroup) => (
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
    )
}

function filterFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e) => !!e) as InsightEditorFilter[]
}
