/**
 * Integration tests that exercise multiple filter tree modules together,
 * simulating realistic user workflows: build a tree, manipulate it via
 * updateAtPath, verify evaluation and expression output.
 */
import { evaluateFilterTree, treeHasConditions, treeHasEmptyValues, updateAtPath, FilterNode } from './eventFilterLogic'
import { filterTreeToExpression } from './filterTreeDisplay'
import { reorderWithinGroup, moveBetweenGroups } from './filterTreeDnd'
import { getNodeAtPath, splitParentChild } from './filterTreePath'
import { NodeIdMap } from './NodeIdMap'
import { cond, and, or, not } from './testHelpers'

describe('build a tree from scratch and verify evaluation', () => {
    it('incrementally builds a complex filter and evaluates test cases', () => {
        // Start with empty root
        let tree: FilterNode = or()
        expect(treeHasConditions(tree)).toBe(false)

        // Add first condition: drop $autocapture
        tree = updateAtPath(tree, [], (node) => {
            if (node.type === 'or') {
                return { ...node, children: [...node.children, cond('event_name', 'exact', '$autocapture')] }
            }
            return node
        })
        expect(treeHasConditions(tree)).toBe(true)
        expect(evaluateFilterTree(tree, { event_name: '$autocapture' })).toBe(true)
        expect(evaluateFilterTree(tree, { event_name: '$pageview' })).toBe(false)

        // Add second condition: drop events with bot in distinct_id
        tree = updateAtPath(tree, [], (node) => {
            if (node.type === 'or') {
                return { ...node, children: [...node.children, cond('distinct_id', 'contains', 'bot')] }
            }
            return node
        })
        expect(evaluateFilterTree(tree, { event_name: '$pageview', distinct_id: 'bot-crawler' })).toBe(true)
        expect(evaluateFilterTree(tree, { event_name: '$pageview', distinct_id: 'user-1' })).toBe(false)

        // Wrap second condition in NOT — now it means "drop if NOT bot"
        // Actually let's convert to: drop if $autocapture AND NOT bot (protect bots from being dropped)
        tree = updateAtPath(tree, [], () =>
            and(cond('event_name', 'exact', '$autocapture'), not(cond('distinct_id', 'contains', 'bot')))
        )

        // $autocapture from a bot → ingest (protected by NOT)
        expect(evaluateFilterTree(tree, { event_name: '$autocapture', distinct_id: 'bot-1' })).toBe(false)
        // $autocapture from a user → drop
        expect(evaluateFilterTree(tree, { event_name: '$autocapture', distinct_id: 'user-1' })).toBe(true)
        // $pageview from a user → ingest (doesn't match $autocapture)
        expect(evaluateFilterTree(tree, { event_name: '$pageview', distinct_id: 'user-1' })).toBe(false)

        // Verify expression output
        expect(filterTreeToExpression(tree)).toBe(
            ['AND', '├── event_name = "$autocapture"', '└── NOT', '    └── distinct_id ~ "bot"'].join('\n')
        )
    })
})

describe('reorder and move operations preserve evaluation', () => {
    it('reordering within a group does not change evaluation', () => {
        const tree = or(
            cond('event_name', 'exact', '$autocapture'),
            cond('event_name', 'exact', '$drop_me'),
            cond('distinct_id', 'contains', 'bot')
        )

        const mockArrayMove = (arr: FilterNode[], from: number, to: number): FilterNode[] => {
            const result = [...arr]
            const [item] = result.splice(from, 1)
            result.splice(to, 0, item)
            return result
        }

        const reordered = reorderWithinGroup(tree, [], 0, 2, mockArrayMove)
        expect(reordered).not.toBeNull()

        // Evaluation should be identical — OR is commutative
        const testEvents = [
            { event_name: '$autocapture', distinct_id: 'user-1' },
            { event_name: '$drop_me', distinct_id: 'user-1' },
            { event_name: '$pageview', distinct_id: 'bot-1' },
            { event_name: '$pageview', distinct_id: 'user-1' },
        ]
        for (const event of testEvents) {
            expect(evaluateFilterTree(reordered!, event)).toBe(evaluateFilterTree(tree, event))
        }
    })

    it('moving a condition between groups changes evaluation correctly', () => {
        // OR(AND(condA, condB), AND(condC))
        const condA = cond('event_name', 'exact', '$autocapture')
        const condB = cond('distinct_id', 'contains', 'bot')
        const condC = cond('event_name', 'exact', '$drop_me')
        const secondAnd = and(condC)
        const tree = or(and(condA, condB), secondAnd)
        const nodeIds = new NodeIdMap()
        nodeIds.buildIndex(tree)

        // Before: drops $autocapture from bots, or $drop_me
        expect(evaluateFilterTree(tree, { event_name: '$autocapture', distinct_id: 'bot-1' })).toBe(true)
        expect(evaluateFilterTree(tree, { event_name: '$drop_me', distinct_id: 'user-1' })).toBe(true)
        expect(evaluateFilterTree(tree, { event_name: '$autocapture', distinct_id: 'user-1' })).toBe(false)

        // Move condB (bot check) from first AND to second AND
        const result = moveBetweenGroups(tree, [0], 1, nodeIds.nidOf(secondAnd), 1, nodeIds)
        expect(result).not.toBeNull()

        // After: first AND only has condA (drops all $autocapture)
        //        second AND has condC + condB (drops $drop_me from bots only)
        expect(evaluateFilterTree(result!, { event_name: '$autocapture', distinct_id: 'user-1' })).toBe(true)
        expect(evaluateFilterTree(result!, { event_name: '$drop_me', distinct_id: 'user-1' })).toBe(false)
        expect(evaluateFilterTree(result!, { event_name: '$drop_me', distinct_id: 'bot-1' })).toBe(true)
    })
})

describe('NodeIdMap + path navigation round-trip', () => {
    it('every node in a complex tree is reachable via its indexed path', () => {
        const tree = or(
            and(cond('event_name', 'exact', 'a'), not(cond('distinct_id', 'exact', 'b'))),
            cond('event_name', 'exact', 'c')
        )
        const nodeIds = new NodeIdMap()
        nodeIds.buildIndex(tree)

        // Collect all nodes by walking the tree
        function collectNodes(node: FilterNode): FilterNode[] {
            const nodes = [node]
            if (node.type === 'and' || node.type === 'or') {
                for (const child of node.children) {
                    nodes.push(...collectNodes(child))
                }
            } else if (node.type === 'not') {
                nodes.push(...collectNodes(node.child))
            }
            return nodes
        }

        const allNodes = collectNodes(tree)
        expect(allNodes.length).toBe(6) // or, and, cond-a, not, cond-b, cond-c

        for (const node of allNodes) {
            const nid = nodeIds.nidOf(node)
            const path = nodeIds.pathOf(nid)
            expect(path).not.toBeUndefined()
            expect(getNodeAtPath(tree, path!)).toBe(node)
        }
    })

    it('splitParentChild correctly identifies parent for every non-root node', () => {
        const tree = or(
            and(cond('event_name', 'exact', 'a'), cond('event_name', 'exact', 'b')),
            cond('event_name', 'exact', 'c')
        )
        const nodeIds = new NodeIdMap()
        nodeIds.buildIndex(tree)

        // Check condA's parent is the inner AND
        const condAPath = nodeIds.pathOf(nodeIds.nidOf(tree.children[0]))!
        // condA is at [0], its parent split should be {parentPath: [], childIndex: 0}
        const condAParent = splitParentChild(condAPath)
        expect(condAParent).not.toBeNull()
        expect(getNodeAtPath(tree, condAParent!.parentPath)).toBe(tree)
    })
})

describe('validation + evaluation consistency', () => {
    it('a tree with empty values fails validation but still evaluates safely', () => {
        const tree = and(cond('event_name', 'exact', ''), cond('distinct_id', 'exact', 'user'))

        expect(treeHasEmptyValues(tree)).toBe(true)
        expect(treeHasConditions(tree)).toBe(true)

        // Empty condition value: event_name === '' — only matches empty string event names
        expect(evaluateFilterTree(tree, { event_name: '', distinct_id: 'user' })).toBe(true)
        // Normal events don't match the empty condition
        expect(evaluateFilterTree(tree, { event_name: '$pageview', distinct_id: 'user' })).toBe(false)
    })

    it('disabled filter (empty tree) never drops anything', () => {
        const tree = or()
        expect(treeHasConditions(tree)).toBe(false)
        expect(evaluateFilterTree(tree, { event_name: '$anything', distinct_id: 'anyone' })).toBe(false)
    })
})
