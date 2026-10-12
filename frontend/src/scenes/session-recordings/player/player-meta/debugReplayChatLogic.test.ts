import { MAX_SIDE_PANEL_ID } from 'scenes/max/components/PhaiSidePanelChat'

import { initKeaTests } from '~/test/init'

import { ActiveCreation, runnerPanelLogic } from 'products/posthog_ai/frontend/api/logics'

import { debugReplayChatLogic } from './debugReplayChatLogic'

describe('debugReplayChatLogic', () => {
    let logic: ReturnType<typeof debugReplayChatLogic.build>
    let panel: ReturnType<typeof runnerPanelLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = debugReplayChatLogic()
        logic.mount()
        panel = runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID })
    })

    afterEach(() => {
        logic?.unmount()
    })

    test.each<[string, ActiveCreation[], Record<string, string>]>([
        [
            'the task the panel creates for the debug prompt',
            [{ streamKey: 'draft-1' }, { streamKey: 'draft-1', taskId: 'task-1', runId: 'run-1' }],
            { 'session-1': 'task-1' },
        ],
        ['no task when the user opens another chat from history', [{ streamKey: 'run-9', taskId: 'task-9' }], {}],
        [
            'no task when the user leaves the pending run for another chat',
            [{ streamKey: 'draft-1' }, { streamKey: 'run-9', taskId: 'task-9', runId: 'run-9' }],
            {},
        ],
    ])('remembers %s', (_, creations, expected) => {
        logic.actions.debugChatRequested('session-1')
        for (const creation of creations) {
            panel.actions.setActiveCreation(creation)
        }
        expect(logic.values.taskIdBySessionRecordingId).toEqual(expected)
    })
})
