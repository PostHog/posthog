import { act, cleanup, renderHook } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { foregroundStreamLogic, toolStreamEventsLogic } from 'products/posthog_ai/frontend/api/logics'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/api/types'

import { useFeatureFlagAgentRefresh } from './useFeatureFlagAgentRefresh'

const STREAM_KEY = 'run-1'

function completedToolCall(
    toolName: string,
    args: string,
    source: ToolStreamEvent['source'] = 'live'
): ToolStreamEvent {
    return {
        streamKey: STREAM_KEY,
        toolCallId: `${toolName}-${args}`,
        toolName,
        rawToolName: 'exec',
        phase: 'completed',
        invocation: {
            rawServerName: 'posthog',
            rawToolName: 'exec',
            input: { command: `call ${toolName} ${args}` },
        } as unknown as ToolStreamEvent['invocation'],
        source,
    }
}

describe('useFeatureFlagAgentRefresh', () => {
    beforeEach(() => {
        initKeaTests(false)
    })

    afterEach(() => {
        cleanup()
    })

    function watchFlag(flagId: number | null): jest.Mock {
        const onAgentChange = jest.fn()
        renderHook(() => useFeatureFlagAgentRefresh({ flagId, onAgentChange }))
        act(() => {
            // What sending a prompt from this page leaves behind: the watched run, target claimed.
            foregroundStreamLogic.actions.setForegroundStream(STREAM_KEY, 'side-panel')
            toolStreamEventsLogic.actions.claimApplyBackTargets(STREAM_KEY)
        })
        return onAgentChange
    }

    function emit(event: ToolStreamEvent): void {
        act(() => {
            toolStreamEventsLogic.actions.emitToolEvent(event)
        })
    }

    it('reacts once per completed lifecycle call that changed the open flag', () => {
        const onAgentChange = watchFlag(1)

        emit(completedToolCall('feature-flag-disable', '{"id":"1"}'))
        expect(onAgentChange).toHaveBeenCalledTimes(1)

        // A turn that changes this flag and then another one still has to refresh this page.
        emit(completedToolCall('update-feature-flag', '{"id":1,"name":"Renamed by the agent"}'))
        expect(onAgentChange).toHaveBeenCalledTimes(2)

        // Another flag's call must not refresh this page.
        emit(completedToolCall('feature-flag-archive', '{"id":7}'))
        expect(onAgentChange).toHaveBeenCalledTimes(2)
    })

    it('ignores a replayed call, so reopening the page does not refresh it again', () => {
        const onAgentChange = watchFlag(1)

        emit(completedToolCall('feature-flag-disable', '{"id":1}', 'replay'))

        expect(onAgentChange).not.toHaveBeenCalled()
    })

    it('ignores tool calls while the flag is unsaved or unloaded', () => {
        const onAgentChange = watchFlag(null)

        emit(completedToolCall('update-feature-flag', '{"id":1}'))

        expect(onAgentChange).not.toHaveBeenCalled()
    })
})
