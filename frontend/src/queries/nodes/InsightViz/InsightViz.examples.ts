import { InsightVizNode, NodeKind } from '~/queries/schema'

const AllDefaults: InsightVizNode = {
    kind: NodeKind.InsightVizNode,
    source: { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode, name: '$pageview' }] },
}

const Minimalist: InsightVizNode = {
    kind: NodeKind.InsightVizNode,
    source: { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode, name: '$pageview' }] },
    full: false,
}
export const examples = {
    AllDefaults,
    Minimalist,
}
