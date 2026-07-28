import type { NotebookComponentRunStatus } from 'lib/components/MarkdownNotebook'
import type { NotebookComponentBlockNode, NotebookComponentProps } from 'lib/components/MarkdownNotebook/types'

import { resolveNotebookComponentRunStatus } from './markdownNotebookRunStatus'
import type { NotebookNodeRunTerminalStatus } from './notebookNodeStalenessLogic'

describe('markdownNotebookRunStatus', () => {
    const sqlCell = (props: NotebookComponentProps = {}, tagName = 'SQLV2'): NotebookComponentBlockNode => ({
        id: 'block-fingerprint',
        type: 'component',
        tagName,
        props,
    })

    const cases: {
        label: string
        node: NotebookComponentBlockNode
        staleNodeIds?: Record<string, true>
        nodeRunStatuses?: Record<string, NotebookNodeRunTerminalStatus>
        expected: NotebookComponentRunStatus
    }[] = [
        { label: 'a block that cannot run', node: sqlCell({}, 'Query'), expected: 'idle' },
        { label: 'a cell that has never run', node: sqlCell(), expected: 'idle' },
        {
            label: 'a successful run',
            node: sqlCell({ nodeId: 'node-1' }),
            nodeRunStatuses: { 'node-1': 'done' },
            expected: 'success',
        },
        {
            label: 'a failed run',
            node: sqlCell({ nodeId: 'node-1' }),
            nodeRunStatuses: { 'node-1': 'failed' },
            expected: 'error',
        },
        {
            label: 'an interrupted run',
            node: sqlCell({ nodeId: 'node-1' }),
            nodeRunStatuses: { 'node-1': 'interrupted' },
            expected: 'error',
        },
        {
            label: 'a cell an upstream re-run outdated',
            node: sqlCell({ nodeId: 'node-1' }),
            staleNodeIds: { 'node-1': true },
            nodeRunStatuses: { 'node-1': 'done' },
            expected: 'stale',
        },
        {
            // The failure, not the staleness, is what the user has to act on.
            label: 'a stale cell whose last run failed',
            node: sqlCell({ nodeId: 'node-1' }),
            staleNodeIds: { 'node-1': true },
            nodeRunStatuses: { 'node-1': 'failed' },
            expected: 'error',
        },
        {
            // Run outcomes don't survive a reload, but the result the run persisted does.
            label: 'a reloaded cell with a persisted result',
            node: sqlCell({ nodeId: 'node-1', result: { row_count: 1 } }),
            expected: 'success',
        },
        {
            label: 'a reloaded cell with no persisted result',
            node: sqlCell({ nodeId: 'node-1', result: null }),
            expected: 'idle',
        },
        {
            label: 'a cell that has not pinned an id yet, by its block id',
            node: sqlCell(),
            nodeRunStatuses: { 'block-fingerprint': 'done' },
            expected: 'success',
        },
        {
            label: 'a cell that pinned an id, by that id rather than its block id',
            node: sqlCell({ nodeId: 'node-1' }),
            nodeRunStatuses: { 'block-fingerprint': 'done' },
            expected: 'idle',
        },
    ]

    it.each(cases)('resolves $label', ({ node, staleNodeIds, nodeRunStatuses, expected }) => {
        expect(resolveNotebookComponentRunStatus(node, staleNodeIds ?? {}, nodeRunStatuses ?? {})).toBe(expected)
    })
})
