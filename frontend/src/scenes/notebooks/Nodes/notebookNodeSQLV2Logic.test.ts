import { NotebookNodeType } from '../types'
import { collectSqlV2Refs } from './notebookNodeSQLV2Logic'

describe('collectSqlV2Refs', () => {
    const sqlNode = (nodeId: string, name: string, code: string): Record<string, unknown> => ({
        type: NotebookNodeType.SQLV2,
        attrs: { nodeId, name, code },
    })

    const doc = (...children: Record<string, unknown>[]): Record<string, unknown> => ({
        type: 'doc',
        content: children,
    })

    it('collects named siblings but excludes the running node itself', () => {
        // Including self would inline the node as a CTE of its own name — a cycle the backend rejects.
        const document = doc(
            sqlNode('a', 'df1', 'select id from events'),
            sqlNode('self', 'df2', 'select * from df1'),
            sqlNode('c', 'df3', 'select id from persons')
        )
        expect(collectSqlV2Refs(document, 'self')).toEqual({
            df1: 'select id from events',
            df3: 'select id from persons',
        })
    })

    it('skips nodes without a name or without code', () => {
        const document = doc(sqlNode('a', '', 'select 1'), sqlNode('b', '  ', 'select 2'), sqlNode('c', 'df', '   '))
        expect(collectSqlV2Refs(document, 'self')).toEqual({})
    })

    it('finds SQLV2 nodes nested inside other content', () => {
        const document = doc({ type: 'column', content: [sqlNode('a', 'df1', 'select 1')] })
        expect(collectSqlV2Refs(document, 'self')).toEqual({ df1: 'select 1' })
    })
})
