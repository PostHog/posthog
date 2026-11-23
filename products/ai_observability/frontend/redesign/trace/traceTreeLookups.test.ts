import type { TraceNodeApi } from '../../generated/api.schemas'
import { makeTraceResource } from './testFixtures'
import { firstFailingNodeId, steppedNodeId } from './traceTreeLookups'

function node(id: string, children: TraceNodeApi[] = []): TraceNodeApi {
    const [root] = makeTraceResource().tree
    return { ...root, id, name: id, label: id, kind: 'span', children }
}

describe('traceTreeLookups', () => {
    test('firstFailingNodeId walks the tree in order and skips ids outside it', () => {
        const tree = [node('root', [node('span-a', [node('gen-1')]), node('gen-2')])]

        expect(
            firstFailingNodeId(
                tree,
                new Map([
                    ['gen-2', 'fail'],
                    ['gen-1', 'fail'],
                    ['ghost', 'fail'],
                ])
            )
        ).toBe('gen-1')
        expect(
            firstFailingNodeId(
                tree,
                new Map([
                    ['ghost', 'fail'],
                    ['gen-2', 'pass'],
                ])
            )
        ).toBeNull()
    })

    test.each([
        ['root', 'next', 'span-a'],
        ['gen-1', 'next', 'gen-2'],
        ['gen-2', 'previous', 'gen-1'],
        ['root', 'previous', null],
        ['gen-2', 'next', null],
        ['gen-1', 'first', 'root'],
        ['root', 'first', null],
        ['root', 'last', 'gen-2'],
        ['gen-1', 'parent', 'span-a'],
        ['root', 'parent', null],
        ['span-a', 'child', 'gen-1'],
        ['gen-1', 'child', null],
        ['ghost', 'next', 'root'],
        ['ghost', 'previous', 'root'],
    ] as const)('steppedNodeId from %s going %s is %s', (from, step, expected) => {
        const tree = [node('root', [node('span-a', [node('gen-1')]), node('gen-2')])]

        expect(steppedNodeId(tree, from, step)).toBe(expected)
    })
})
