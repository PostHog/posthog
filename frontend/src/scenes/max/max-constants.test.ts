import { AgentMode, TaskExecutionStatus } from '~/queries/schema/schema-assistant-messages'

import { EnhancedToolCall, TOOL_DEFINITIONS, getToolsForMode } from './max-constants'

function scanToolCall(results: { session_id: string; scan_outcome: string }[]): EnhancedToolCall {
    return {
        id: 'call-1',
        name: 'scan_replay_vision_sessions',
        args: {},
        status: TaskExecutionStatus.Completed,
        result: {
            type: 'tool' as any,
            content: '',
            tool_call_id: 'call-1',
            ui_payload: { scan_replay_vision_sessions: { scan_id: 'scanner-1', results } },
        },
    } as unknown as EnhancedToolCall
}

function widgetArgs(results: { session_id: string; scan_outcome: string }[]): any {
    const formatted = TOOL_DEFINITIONS.scan_replay_vision_sessions.displayFormatter?.(scanToolCall(results), {
        registeredToolMap: {},
    })
    return Array.isArray(formatted) ? formatted[1]?.args : undefined
}

function searchIssuesLabel(ui_payload: Record<string, any> | undefined): unknown {
    const toolCall = {
        id: 'call-1',
        name: 'search_error_tracking_issues',
        args: {},
        status: TaskExecutionStatus.Completed,
        result: { type: 'tool' as any, content: '', tool_call_id: 'call-1', ui_payload },
    } as unknown as EnhancedToolCall
    return TOOL_DEFINITIONS.search_error_tracking_issues.displayFormatter?.(toolCall, { registeredToolMap: {} })
}

describe('max-constants', () => {
    it.each([
        [{ search_error_tracking_issues: { issues: [{ id: 'issue-1' }] } }, 'Found issues'],
        [{ search_error_tracking_issues: { issues: [] } }, 'No issues found'],
        [undefined, 'Searched issues'],
    ])('labels an error tracking search by its result %#', (ui_payload, expected) => {
        expect(searchIssuesLabel(ui_payload)).toEqual(expected)
    })

    it('waits only on outcomes that produce an observation', () => {
        const args = widgetArgs([
            { session_id: 'a', scan_outcome: 'started' },
            { session_id: 'b', scan_outcome: 'already_scanned' },
            { session_id: 'c', scan_outcome: 'skipped_quota' },
        ])

        expect(args.sessionIds).toEqual(['a', 'b'])
        expect(args.skipped).toEqual([{ sessionId: 'c', reason: 'skipped_quota' }])
    })

    it('reports an unrecognized outcome instead of waiting on it', () => {
        // A denylist would treat a new backend outcome as in flight, so the widget would wait on a
        // recording that never gets a row.
        const args = widgetArgs([{ session_id: 'a', scan_outcome: 'some_future_outcome' }])

        expect(args.sessionIds).toEqual([])
        expect(args.skipped).toEqual([{ sessionId: 'a', reason: 'some_future_outcome' }])
    })

    it('does not offer the retired session summarization tool in any mode', () => {
        // The tool is gone; the definition only remains so old conversations still render its calls.
        const offered = Object.values(AgentMode).flatMap((mode) => getToolsForMode(mode).map((tool) => tool.name))

        expect(offered).not.toContain(TOOL_DEFINITIONS.summarize_sessions.name)
    })
})
