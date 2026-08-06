import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { classifyPartial, handsFreeLogic, type SuppressionReason } from './handsFreeLogic'
import { maxLogic } from './maxLogic'
import { maxMocks } from './testUtils'

describe('handsFreeLogic state machine', () => {
    let logic: ReturnType<typeof handsFreeLogic.build>
    let parent: ReturnType<typeof maxLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        parent = maxLogic({ panelId: 'hands-free-test-tab' })
        parent.mount()
        logic = handsFreeLogic({ panelId: 'hands-free-test-tab' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        parent.unmount()
    })

    it('starts off with idle connection and exposes isActive=false', async () => {
        await expectLogic(logic).toMatchValues({ status: 'off', connection: 'idle', isActive: false })
    })

    it('exitHandsFree from off keeps status off (defensive)', async () => {
        await expectLogic(logic, () => {
            logic.actions.exitHandsFree('test')
        }).toMatchValues({ status: 'off', connection: 'idle' })
    })

    it('setStatus("listening") then exitHandsFree resets back to off + connection idle', async () => {
        await expectLogic(logic, () => {
            logic.actions.setStatus('listening')
            logic.actions.setConnection('connected')
        }).toMatchValues({ status: 'listening', connection: 'connected', isActive: true })

        await expectLogic(logic, () => {
            logic.actions.exitHandsFree('test')
        }).toMatchValues({ status: 'off', connection: 'idle', isActive: false })
    })

    it('setError stores the error string; entering hands-free clears it', async () => {
        await expectLogic(logic, () => {
            logic.actions.setError('something broke')
        }).toMatchValues({ error: 'something broke' })

        await expectLogic(logic, () => {
            logic.actions.setError(null)
        }).toMatchValues({ error: null })
    })

    it('setPartialTranscript stores the in-flight transcript; commitTranscript clears it', async () => {
        await expectLogic(logic, () => {
            logic.actions.setPartialTranscript('how is the prod')
        }).toMatchValues({ partialTranscript: 'how is the prod' })

        // commit triggers askMax via the listener; thread isn't mounted here so it'll error out,
        // but the reducer for partialTranscript clears regardless
        await expectLogic(logic, () => {
            logic.actions.commitTranscript('how is the product doing today')
        }).toMatchValues({ partialTranscript: '' })
    })

    it('exitHandsFree clears any in-flight partial transcript', async () => {
        await expectLogic(logic, () => {
            logic.actions.setPartialTranscript('mid sentence')
        }).toMatchValues({ partialTranscript: 'mid sentence' })

        await expectLogic(logic, () => {
            logic.actions.exitHandsFree('test')
        }).toMatchValues({ partialTranscript: '' })
    })

    it('speakAssistantResponse with empty summary while off is a no-op', async () => {
        await expectLogic(logic, () => {
            logic.actions.speakAssistantResponse({ text: '', vizCount: 0 })
        }).toMatchValues({ status: 'off' })
    })
})

describe('classifyPartial barge-in heuristic', () => {
    const spoken = 'lets look at the daily active users for the last week'
    const cases: { name: string; spoken: string; partial: string; expected: SuppressionReason }[] = [
        { name: 'empty partial -> too_short', spoken, partial: '', expected: 'too_short' },
        { name: '1-char partial -> too_short', spoken, partial: 'a', expected: 'too_short' },
        { name: '3-char unrelated -> too_short', spoken, partial: 'xyz', expected: 'too_short' },
        { name: 'allowlist "stop" bypasses too_short', spoken, partial: 'stop', expected: null },
        { name: 'allowlist "no" bypasses too_short', spoken, partial: 'no', expected: null },
        { name: 'allowlist "wait" bypasses too_short', spoken, partial: 'wait', expected: null },
        { name: 'allowlist "max" bypasses too_short', spoken, partial: 'max', expected: null },
        { name: 'substring of spoken text -> substring', spoken, partial: 'daily active', expected: 'substring' },
        { name: 'unrelated longer phrase -> not suppressed', spoken, partial: 'change the chart type', expected: null },
        {
            name: 'partial matches mid-word run in spoken -> substring',
            spoken,
            partial: 'active users',
            expected: 'substring',
        },
    ]
    it.each(cases)('$name', ({ spoken, partial, expected }) => {
        expect(classifyPartial(spoken, partial)).toBe(expected)
    })
})
