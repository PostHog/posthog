import { FilterType, InsightLogicProps } from '~/types'
import React, { useMemo } from 'react'
import { BindLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useValues } from 'kea'
import { InsightViz } from 'lib/components/InsightCard/InsightCard'

let uniqueMemoizedIndex = 0
export function AdHocInsight({
    filters,
    style,
}: {
    filters: Partial<FilterType>
    style: React.CSSProperties
}): JSX.Element {
    const pageKey = useMemo(() => `filter-${uniqueMemoizedIndex++}`, [])
    const props: InsightLogicProps = {
        dashboardItemId: `new-adhoc-${pageKey}`,
        cachedInsight: {
            filters,
        },
    }
    const logic = insightLogic(props)
    const { insight } = useValues(logic)

    return (
        <BindLogic logic={insightLogic} props={props}>
            <div style={{ position: 'relative', ...style }}>
                <InsightViz insight={insight as any} style={{ top: 0, left: 0 }} />
            </div>
        </BindLogic>
    )
}
