import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import * as featureFlagLogic from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { endpointsRunCreate } from 'products/endpoints/frontend/generated/api'

import { accountContextLogic } from './accountContextLogic'
import { AccountsEvents } from './constants'

jest.mock('products/endpoints/frontend/generated/api', () => ({
    ...jest.requireActual('products/endpoints/frontend/generated/api'),
    endpointsRunCreate: jest.fn(),
}))

const runEndpoint = jest.mocked(endpointsRunCreate)

const SOURCE = { project_id: 42, endpoint: 'account-context', account_variable: 'account_key' }
const EXTERNAL_ID = 'external-account-1'

const RESPONSE = {
    name: 'account-context',
    columns: ['section', 'id', 'fact_text', 'confidence', 'review_due'],
    results: [
        ['fact', 'fact-confirmed', 'A confirmed fact', 'confirmed', 0],
        ['fact', 'fact-inferred', 'An inferred fact', 'inferred', 1],
    ],
}

describe('accountContextLogic', () => {
    let logic: ReturnType<typeof accountContextLogic.build>

    beforeEach(() => {
        initKeaTests()
        runEndpoint.mockReset()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    function mountWith(payload: unknown): void {
        jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue(payload)
        logic = accountContextLogic({ accountId: 'account-1', externalId: EXTERNAL_ID })
        logic.mount()
    }

    it('sends no request when no context source is configured', async () => {
        mountWith(null)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.contextResult).toEqual({ status: 'not_configured' })
        expect(runEndpoint).not.toHaveBeenCalled()
    })

    it('loads the account from the configured source and filters its facts', async () => {
        runEndpoint.mockResolvedValue(RESPONSE)
        mountWith(SOURCE)
        await expectLogic(logic).toFinishAllListeners()

        expect(runEndpoint).toHaveBeenCalledWith('42', 'account-context', { variables: { account_key: EXTERNAL_ID } })
        expect(logic.values.visibleFacts.map((fact) => fact.id)).toEqual(['fact-confirmed'])

        logic.actions.setFactConfidence('inferred')
        logic.actions.setRecheckOnly(true)
        expect(logic.values.visibleFacts.map((fact) => fact.id)).toEqual(['fact-inferred'])
    })

    it('keeps account data out of telemetry when a load fails, and recovers on retry', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        const captureException = jest.spyOn(posthog, 'captureException')
        runEndpoint.mockRejectedValueOnce(new Error('Gateway timeout'))
        mountWith(SOURCE)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.contextResult).toEqual({ status: 'failed' })
        expect(captureException).toHaveBeenCalledWith(expect.any(Error), { scope: 'accountContextLogic.loadContext' })
        expect(capture).toHaveBeenCalledWith(AccountsEvents.ContextLoadFailed)

        runEndpoint.mockResolvedValue(RESPONSE)
        logic.actions.loadContext()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.contextResult?.status).toBe('loaded')
        expect(JSON.stringify([capture.mock.calls, captureException.mock.calls])).not.toContain(EXTERNAL_ID)
    })
})
