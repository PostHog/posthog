import { NotebookNodeType } from 'scenes/notebooks/types'

import { VisualizationBlock } from '~/queries/schema/schema-assistant-artifacts'
import { DataVisualizationNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { blocksToTiptapContent } from './blocksToTiptapContent'

describe('blocksToTiptapContent', () => {
    const hogQLQuery = { kind: NodeKind.HogQLQuery, query: 'SELECT 1' } as const

    it.each([
        [
            'a SQL chart stays a DataVisualizationNode',
            { kind: NodeKind.DataVisualizationNode, source: hogQLQuery, display: ChartDisplayType.ActionsTable },
            NodeKind.DataVisualizationNode,
            NodeKind.HogQLQuery,
        ],
        [
            'a bare HogQL query gets a DataVisualizationNode shell',
            hogQLQuery,
            NodeKind.DataVisualizationNode,
            NodeKind.HogQLQuery,
        ],
        [
            'an insight query gets an InsightVizNode shell',
            { kind: NodeKind.TrendsQuery, series: [] },
            NodeKind.InsightVizNode,
            NodeKind.TrendsQuery,
        ],
    ])('%s', (_name, query, expectedKind, expectedSourceKind) => {
        const nodes = blocksToTiptapContent([{ type: 'visualization', query } as VisualizationBlock])

        expect(nodes).toHaveLength(1)
        expect(nodes[0].type).toEqual(NotebookNodeType.Query)

        const notebookQuery = nodes[0].attrs?.query as DataVisualizationNode | InsightVizNode
        expect(notebookQuery.kind).toEqual(expectedKind)
        expect(notebookQuery.source.kind).toEqual(expectedSourceKind)
    })
})
