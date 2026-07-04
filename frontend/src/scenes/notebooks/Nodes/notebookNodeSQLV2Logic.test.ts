import { NotebookNodeType } from '../types'
import { collectSqlV2Refs } from './notebookNodeSQLV2Logic'

describe('collectSqlV2Refs', () => {
    const sqlNode = (nodeId: string, returnVariable: string): Record<string, unknown> => ({
        type: NotebookNodeType.SQLV2,
        attrs: { nodeId, returnVariable },
    })

    const doc = (...children: Record<string, unknown>[]): Record<string, unknown> => ({
        type: 'doc',
        content: children,
    })

    it('maps each named sibling to its node id, excluding the running node itself', () => {
        // Including self would inline the node as a CTE of its own name — a cycle the backend rejects.
        const document = doc(sqlNode('a', 'df1'), sqlNode('self', 'df2'), sqlNode('c', 'df3'))
        expect(collectSqlV2Refs(document, 'self')).toEqual({ df1: 'a', df3: 'c' })
    })

    it('skips nodes with a blank name', () => {
        const document = doc(sqlNode('a', ''), sqlNode('b', '  '))
        expect(collectSqlV2Refs(document, 'self')).toEqual({})
    })

    it('finds SQLV2 nodes nested inside other content', () => {
        const document = doc({ type: 'column', content: [sqlNode('a', 'df1')] })
        expect(collectSqlV2Refs(document, 'self')).toEqual({ df1: 'a' })
    })
})
