import type { TraceNodeApi } from '../../../generated/api.schemas'
import { makeTraceResource } from './testFixtures'
import { firstFailingNodeId, toEvalsChip } from './toEvalSummary'

function node(id: string, children: TraceNodeApi[] = []): TraceNodeApi {
    const [root] = makeTraceResource().tree
    return { ...root, id, name: id, kind: 'span', children }
}

describe('toEvalSummary', () => {
    test.each([
        ['all graded', { passed: 4, failed: 1, unrated: 0 }, { passed: 4, graded: 5, unrated: 0 }],
        ['only unrated', { passed: 0, failed: 0, unrated: 3 }, { passed: 0, graded: 0, unrated: 3 }],
        ['nothing', { passed: 0, failed: 0, unrated: 0 }, null],
    ])('toEvalsChip with %s', (_, counts, expected) => {
        expect(toEvalsChip({ ...counts, nodes: [] })).toEqual(expected)
    })

    test('firstFailingNodeId walks the tree in order and skips ids outside it', () => {
        const tree = [node('root', [node('span-a', [node('gen-1')]), node('gen-2')])]

        expect(firstFailingNodeId(tree, { 'gen-2': 'fail', 'gen-1': 'fail', ghost: 'fail' })).toBe('gen-1')
        expect(firstFailingNodeId(tree, { ghost: 'fail', 'gen-2': 'pass' })).toBeNull()
    })
})
