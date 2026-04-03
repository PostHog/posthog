import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FunnelPathType } from '~/types'

import { journeyEditorLogic } from './journeyEditorLogic'

describe('journeyEditorLogic', () => {
    let logic: ReturnType<typeof journeyEditorLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = journeyEditorLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    const expansionX = { stepIndex: 0, pathType: FunnelPathType.before, dropOff: false }
    const expansionY = { stepIndex: 2, pathType: FunnelPathType.after, dropOff: false }

    describe('expansionContext', () => {
        it('sets context on first stage', async () => {
            await expectLogic(logic, () => {
                logic.actions.stagePathNode('path-0_foo', 'foo', expansionX, 3)
            }).toMatchValues({ expansionContext: { expansion: expansionX, funnelStepCount: 3 } })
        })

        it('resets after unstaging last node then staging from a different expansion', async () => {
            logic.actions.stagePathNode('path-0_foo', 'foo', expansionX, 3)
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.unstagePathNode('path-0_foo')
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.stagePathNode('path-2_bar', 'bar', expansionY, 3)
            }).toMatchValues({ expansionContext: { expansion: expansionY, funnelStepCount: 3 } })
        })

        it('updates context when staging from a new expansion with nodes already staged', async () => {
            logic.actions.stagePathNode('path-0_foo', 'foo', expansionX, 3)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.stagePathNode('path-2_bar', 'bar', expansionY, 3)
            }).toMatchValues({ expansionContext: { expansion: expansionY, funnelStepCount: 3 } })
        })

        it('preserves context when staging multiple nodes from the same expansion', async () => {
            logic.actions.stagePathNode('path-0_foo', 'foo', expansionX, 3)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.stagePathNode('path-1_bar', 'bar', expansionX, 3)
            }).toMatchValues({
                expansionContext: { expansion: expansionX, funnelStepCount: 3 },
                stagedNodes: [
                    { nodeId: 'path-0_foo', eventName: 'foo' },
                    { nodeId: 'path-1_bar', eventName: 'bar' },
                ],
            })
        })

        it('resets on cancelChanges', async () => {
            logic.actions.stagePathNode('path-0_foo', 'foo', expansionX, 3)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.cancelChanges()
            }).toMatchValues({ expansionContext: null })
        })
    })

    describe('insertionIndex', () => {
        it.each([
            ['before step 0 → index 0', { stepIndex: 0, pathType: FunnelPathType.before, dropOff: false }, 3, 0],
            ['between → stepIndex', { stepIndex: 1, pathType: FunnelPathType.between, dropOff: false }, 3, 1],
            ['after → funnelStepCount', { stepIndex: 2, pathType: FunnelPathType.after, dropOff: false }, 5, 5],
        ])('%s', async (_label, expansion, funnelStepCount, expectedIndex) => {
            await expectLogic(logic, () => {
                logic.actions.stagePathNode('path-0_foo', 'foo', expansion, funnelStepCount)
            }).toMatchValues({ insertionIndex: expectedIndex })
        })

        it('uses correct index after unstage-all and re-stage from different expansion', async () => {
            logic.actions.stagePathNode('path-0_foo', 'foo', expansionX, 3)
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.unstagePathNode('path-0_foo')
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.stagePathNode('path-2_bar', 'bar', expansionY, 3)
            }).toMatchValues({ insertionIndex: 3 })
        })
    })

    describe('stagedNodes', () => {
        it('stages and unstages nodes', async () => {
            logic.actions.stagePathNode('path-0_foo', 'foo', expansionX, 3)
            expect(logic.values.stagedNodes).toEqual([{ nodeId: 'path-0_foo', eventName: 'foo' }])

            logic.actions.stagePathNode('path-1_bar', 'bar', expansionX, 3)
            expect(logic.values.stagedNodes).toHaveLength(2)

            logic.actions.unstagePathNode('path-0_foo')
            expect(logic.values.stagedNodes).toEqual([{ nodeId: 'path-1_bar', eventName: 'bar' }])
        })

        it('clears on cancelChanges', () => {
            logic.actions.stagePathNode('path-0_foo', 'foo', expansionX, 3)
            logic.actions.cancelChanges()
            expect(logic.values.stagedNodes).toEqual([])
        })
    })

    describe('sortedStagedNodes', () => {
        it('sorts by layer index extracted from nodeId', () => {
            logic.actions.stagePathNode('path-2_bar', 'bar', expansionX, 3)
            logic.actions.stagePathNode('path-0_foo', 'foo', expansionX, 3)
            logic.actions.stagePathNode('path-1_baz', 'baz', expansionX, 3)

            expect(logic.values.sortedStagedNodes.map((n) => n.nodeId)).toEqual([
                'path-0_foo',
                'path-1_baz',
                'path-2_bar',
            ])
        })
    })
})
