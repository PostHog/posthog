import { initKeaTests } from '~/test/init'

import { toolStreamEventsLogic } from 'products/posthog_ai/frontend/api/logics'
import { foregroundStreamLogic } from 'products/posthog_ai/frontend/logics/foregroundStreamLogic'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/types/streamTypes'

import { biAgentSyncLogic } from './biAgentSyncLogic'
import { biWorksheetsLogic } from './biWorksheetsLogic'

it('refreshes the worksheet library after a completed foreground tool and unregisters on unmount', () => {
    initKeaTests()
    const library = biWorksheetsLogic()
    const unmountLibrary = library.mount()
    const refresh = jest.spyOn(library.actions, 'loadWorksheets')
    const unmountSync = biAgentSyncLogic.mount()
    const bus = toolStreamEventsLogic.findMounted()
    expect(bus).not.toBeNull()
    const unmountBus = bus!.mount()
    try {
        foregroundStreamLogic.actions.setForegroundStream('worksheet-run', 'worksheet-panel')
        const event: ToolStreamEvent = {
            streamKey: 'worksheet-run',
            toolCallId: 'create-worksheet',
            toolName: 'insight-create',
            rawToolName: 'exec',
            phase: 'completed',
            invocation: {} as ToolStreamEvent['invocation'],
            source: 'live',
        }
        bus!.actions.emitToolEvent({ ...event, phase: 'started' })
        expect(refresh).not.toHaveBeenCalled()
        bus!.actions.emitToolEvent(event)
        expect(refresh).toHaveBeenCalledTimes(1)
        unmountSync()
        bus!.actions.emitToolEvent(event)
        expect(refresh).toHaveBeenCalledTimes(1)
    } finally {
        refresh.mockRestore()
        unmountBus()
        unmountLibrary()
    }
})
