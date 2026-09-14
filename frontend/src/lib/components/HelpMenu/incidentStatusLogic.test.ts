import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'lib/logic/preflightLogic'

import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Region } from '~/types'

import { STATUS_PAGE_BASE, incidentStatusLogic } from './incidentStatusLogic'

describe('incidentStatusLogic', () => {
    let logic: ReturnType<typeof incidentStatusLogic.build>
    let fetchSpy: jest.SpyInstance

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    function statusPageRequestCount(): number {
        return fetchSpy.mock.calls.filter((call) => String(call[0]).startsWith(STATUS_PAGE_BASE)).length
    }

    it.each([
        ['once on US cloud', Region.US, 1],
        ['never on a self-hosted deployment', null, 0],
        ['never on local dev', Region.DEV, 0],
    ])('fetches the status page %s', async (_name, region, expectedRequests) => {
        // Preflight resolves after mount here. That is the case which decides whether gating the
        // poll on the region also stops US and EU cloud from ever polling.
        useMocks({ get: { '/_preflight': [200, { ...preflightJson, region }] } })
        initKeaTests()
        fetchSpy = jest.spyOn(global, 'fetch')

        logic = incidentStatusLogic()
        logic.mount()

        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
        await expectLogic(logic).toFinishAllListeners()

        expect(statusPageRequestCount()).toBe(expectedRequests)
        expect(logic.values.summary === null).toBe(expectedRequests === 0)
    })
})
