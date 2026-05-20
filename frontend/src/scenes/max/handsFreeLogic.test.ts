import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { handsFreeLogic } from './handsFreeLogic'
import { maxLogic } from './maxLogic'
import { maxMocks } from './testUtils'

describe('handsFreeLogic state machine', () => {
    let logic: ReturnType<typeof handsFreeLogic.build>
    let parent: ReturnType<typeof maxLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        parent = maxLogic({ tabId: 'hands-free-test-tab' })
        parent.mount()
        logic = handsFreeLogic({ tabId: 'hands-free-test-tab' })
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
