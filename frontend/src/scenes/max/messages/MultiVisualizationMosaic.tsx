import clsx from 'clsx'
import React, { useState } from 'react'

import { IconCollapse, IconExpand, IconEye, IconHide } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import {
    InsightBreakdownSummary,
    PropertiesSummary,
    SeriesSummary,
} from 'lib/components/Cards/InsightCard/InsightDetails'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'

import { Query } from '~/queries/Query/Query'
import { DataVisualizationNode, InsightVizNode } from '~/queries/schema/schema-general'
import { isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'

import type { MultiVisualizationInsight } from './multiVisualizationInsights'

export function MultiVisualizationMosaic({ insights }: { insights: MultiVisualizationInsight[] }): JSX.Element {
    if (insights.length === 1) {
        return (
            <div className="w-full relative">
                <Visualization query={insights[0].query} />
            </div>
        )
    }
    const insightsToShow = insights.slice(0, 4)
    const gridCols = insightsToShow.length === 3 ? 'grid-cols-3' : 'grid-cols-2'
    return (
        <div className={`grid ${gridCols} gap-2`}>
            {insightsToShow.map((insight, index) => (
                // The chart grows with `flex: 1`, so the cell is a fixed-height flex column; a block cell
                // collapses it to a sliver.
                <div key={index} className="relative flex h-[200px] flex-col">
                    <Query query={insight.query} readOnly embedded />
                </div>
            ))}
        </div>
    )
}

const Visualization = React.memo(function Visualization({
    query,
    collapsed,
    editingChildren,
}: {
    query: InsightVizNode | DataVisualizationNode
    collapsed?: boolean
    editingChildren?: React.ReactNode
}): JSX.Element | null {
    const [isSummaryShown, setIsSummaryShown] = useState(false)
    const [isCollapsed, setIsCollapsed] = useState(collapsed ?? false)

    if (!query) {
        return null
    }

    return (
        <>
            {!isCollapsed && <Query query={query} readOnly embedded />}
            <div className={clsx('flex items-center justify-between', !isCollapsed && 'mt-2')}>
                <div className="flex items-center gap-1.5">
                    <LemonButton
                        sideIcon={isSummaryShown ? <IconCollapse /> : <IconExpand />}
                        onClick={() => setIsSummaryShown(!isSummaryShown)}
                        size="xsmall"
                        className="-m-1 shrink"
                        tooltip={isSummaryShown ? 'Hide definition' : 'Show definition'}
                    >
                        <h5 className="m-0 leading-none">
                            <TopHeading query={query} />
                        </h5>
                    </LemonButton>
                </div>
                <div className="flex items-center gap-1.5">
                    {editingChildren}
                    <LemonButton
                        icon={isCollapsed ? <IconEye /> : <IconHide />}
                        onClick={() => setIsCollapsed(!isCollapsed)}
                        size="xsmall"
                        className="-m-1 shrink"
                        tooltip={isCollapsed ? 'Show visualization' : 'Hide visualization'}
                    />
                </div>
            </div>
            {isSummaryShown && !isDataVisualizationNode(query) && (
                <>
                    <SeriesSummary query={query.source} heading={null} />
                    {!isHogQLQuery(query.source) && (
                        <div className="flex flex-wrap gap-4 mt-1 *:grow">
                            <PropertiesSummary properties={query.source.properties} />
                            <InsightBreakdownSummary query={query.source} />
                        </div>
                    )}
                </>
            )}
        </>
    )
})
