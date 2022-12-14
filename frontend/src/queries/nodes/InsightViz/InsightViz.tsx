import { InsightVizNode } from '../../schema'

type InsightVizProps = {
    query: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
}

export function InsightViz({}: InsightVizProps): JSX.Element {
    return <span>InsightViz</span>
}
