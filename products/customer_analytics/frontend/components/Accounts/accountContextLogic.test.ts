import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import * as featureFlagModule from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { endpointsRunCreate } from 'products/endpoints/frontend/generated/api'

import { accountContextResponse } from '../../__mocks__/accountContextResponse'
import { accountContextLogic } from './accountContextLogic'
import { AccountsEvents } from './constants'

jest.mock('products/endpoints/frontend/generated/api', () => ({
    ...jest.requireActual('products/endpoints/frontend/generated/api'),
    endpointsRunCreate: jest.fn(),
}))

const runEndpoint = jest.mocked(endpointsRunCreate)

const SOURCE = { project_id: 42, endpoint: 'account-context', account_variable: 'account_key' }
const EXTERNAL_ID = 'external-account-1'

const RESPONSE = accountContextResponse([
    { section: 'fact', id: 'fact-confirmed', fact_text: 'A confirmed fact', confidence: 'confirmed', review_due: 0 },
    { section: 'fact', id: 'fact-inferred', fact_text: 'An inferred fact', confidence: 'inferred', review_due: 1 },
])

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

    function mountWith(payload: unknown, externalId: string = EXTERNAL_ID): void {
        jest.spyOn(featureFlagModule, 'getFeatureFlagPayload').mockReturnValue(payload)
        logic = accountContextLogic({ accountId: 'account-1', externalId })
        logic.mount()
    }

    it('waits for a context source and loads once the flags arrive', async () => {
        mountWith(null)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.contextResult).toEqual({ status: 'not_configured' })
        expect(runEndpoint).not.toHaveBeenCalled()

        runEndpoint.mockResolvedValue(RESPONSE)
        jest.spyOn(featureFlagModule, 'getFeatureFlagPayload').mockReturnValue(SOURCE)
        featureFlagModule.featureFlagLogic.actions.setFeatureFlags([], {})
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.contextResult?.status).toBe('loaded')
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
        runEndpoint.mockRejectedValueOnce(Object.assign(new Error(`Query failed for ${EXTERNAL_ID}`), { status: 400 }))
        mountWith(SOURCE)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.contextResult).toEqual({ status: 'failed' })
        const [error, properties] = captureException.mock.calls[0]
        expect((error as Error).message).toBe('Account context request failed')
        expect(properties).toEqual({ scope: 'accountContextLogic.loadContext', status: 400 })
        expect(capture).toHaveBeenCalledWith(AccountsEvents.ContextLoadFailed, { reason: 'error' })

        runEndpoint.mockResolvedValue(RESPONSE)
        logic.actions.loadContext()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.contextResult?.status).toBe('loaded')
        expect(capture).toHaveBeenCalledWith(AccountsEvents.ContextLoaded, {
            fact_count: 2,
            signal_count: 0,
            thread_count: 0,
        })
        expect(JSON.stringify([capture.mock.calls, captureException.mock.calls])).not.toContain(EXTERNAL_ID)
    })

    it.each([
        {
            name: 'an account without an external ID',
            externalId: '',
            arrange: (): void => {},
            status: 'no_external_id',
            requests: 0,
            reportedErrors: 0,
        },
        {
            name: 'a viewer without access to the source',
            externalId: EXTERNAL_ID,
            arrange: (): void => {
                runEndpoint.mockRejectedValue(Object.assign(new Error('Forbidden'), { status: 403 }))
            },
            status: 'no_access',
            requests: 1,
            reportedErrors: 0,
        },
        {
            name: 'a response without the expected columns',
            externalId: EXTERNAL_ID,
            arrange: (): void => {
                runEndpoint.mockResolvedValue({ name: 'account-context', columns: ['section', 'id'], results: [] })
            },
            status: 'unreadable',
            requests: 1,
            reportedErrors: 1,
        },
    ])('shows its own state for $name', async ({ externalId, arrange, status, requests, reportedErrors }) => {
        const captureException = jest.spyOn(posthog, 'captureException')
        arrange()
        mountWith(SOURCE, externalId)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.contextResult).toEqual({ status })
        expect(runEndpoint).toHaveBeenCalledTimes(requests)
        expect(captureException).toHaveBeenCalledTimes(reportedErrors)
    })
})
