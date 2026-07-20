import { BindLogic } from 'kea'
import { CSSProperties, useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'
import { TrendInsight } from 'scenes/trends/Trends'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { InsightVizNode } from '~/queries/schema/schema-general'
import { InsightLogicProps, InsightShortId, InsightType, QueryBasedInsightModel } from '~/types'

let uniqueNode = 0

interface InsightVizStoryProps {
    insight: Partial<QueryBasedInsightModel>
    /** Wrapper width in pixels. @default 720 */
    width?: number
    /** Value for `--insight-viz-min-height`, which the chart height floors to. @default '32rem' */
    minHeight?: string
    children?: React.ReactNode
}

/**
 * Mounts an insight viz from a cached insight fixture without the app shell — the lightweight
 * alternative to `createInsightStory` for chart-level visual coverage. Renders the full
 * `TrendInsight` display dispatch by default; pass `children` to mount a specific component
 * (e.g. a non-trends viz like `Paths`) inside the bound logics instead.
 */
export function InsightVizStory({
    insight,
    width = 720,
    minHeight = '32rem',
    children,
}: InsightVizStoryProps): JSX.Element {
    const [dashboardItemId] = useState(() => `InsightVizStory.${uniqueNode++}` as InsightShortId)
    const cachedInsight = { ...insight, short_id: dashboardItemId }
    // Fixtures are loosely typed JSON; every insight fixture is an InsightVizNode with a source
    const source = (cachedInsight.query as InsightVizNode).source

    const insightProps: InsightLogicProps = { dashboardItemId, doNotLoad: true, cachedInsight }
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(cachedInsight, source),
        doNotLoad: true,
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                {/* The viz reads `--insight-viz-min-height` from an `.InsightVizDisplay` ancestor that
                    doesn't exist here — define it so chart heights behave like the real insight page. */}
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div style={{ width, '--insight-viz-min-height': minHeight } as CSSProperties}>
                    {children ?? <TrendInsight view={InsightType.TRENDS} />}
                </div>
            </BindLogic>
        </BindLogic>
    )
}
