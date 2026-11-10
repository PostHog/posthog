import type { TraceNodeApi } from '../../generated/api.schemas'
import { makeTraceResource } from './testFixtures'
import { firstFailingNodeId } from './traceTreeLookups'

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
})
