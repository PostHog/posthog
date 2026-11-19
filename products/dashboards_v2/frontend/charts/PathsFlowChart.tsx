import { useMemo } from 'react'

import { SankeyChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getSeriesColor } from 'lib/colors'

import type { PathsLink } from '~/queries/schema/schema-general'

import { buildPathsGraph } from 'products/product_analytics/frontend/insights/paths/pathsChartData'
import { parsePathNodeKey } from 'products/product_analytics/frontend/insights/paths/pathsChartTransforms'

import { EmptyData } from './EmptyData'

export function PathsFlowChart({ links }: { links: PathsLink[] }): JSX.Element {
    const theme = useChartTheme()
    const graph = useMemo(() => {
        const built = buildPathsGraph({ nodes: [], links }, {}, undefined, {
            node: getSeriesColor(0),
            selectedNode: getSeriesColor(1),
            link: getSeriesColor(0),
        })
        return { ...built, nodes: built.nodes.map((node) => ({ ...node, label: parsePathNodeKey(node.id).name })) }
    }, [links])

    if (!graph.nodes.length) {
        return <EmptyData />
    }
    return (
        <div className="relative flex h-full min-h-0 w-full flex-col" data-attr="dashboard-v2-paths-chart">
            <SankeyChart<unknown, PathsLink> nodes={graph.nodes} links={graph.links} theme={theme} />
        </div>
    )
}
