import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { STATUS_PAGE_BASE } from 'lib/lemon-ui/LemonToast/incidentStatus'
import { preflightLogic } from 'lib/logic/preflightLogic'

import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Region } from '~/types'

import { incidentStatusLogic } from './incidentStatusLogic'

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

    it.each([
        ['without the incident arrays', { page_title: 'PostHog' }],
        [
            'with an incident that has no affected components',
            { ongoing_incidents: [{ name: 'Outage' }], in_progress_maintenances: [] },
        ],
        [
            'with a maintenance that has a non-object component',
            { ongoing_incidents: [], in_progress_maintenances: [{ name: 'Upgrade', affected_components: [null] }] },
        ],
    ])('falls back to operational when the status page returns a 2xx body %s', async (_name, body) => {
        useMocks({ get: { '/_preflight': [200, { ...preflightJson, region: Region.US }] } })
        initKeaTests()
        const realFetch = global.fetch
        fetchSpy = jest
            .spyOn(global, 'fetch')
            .mockImplementation((input, init) =>
                String(input).startsWith(STATUS_PAGE_BASE)
                    ? Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
                    : realFetch(input, init)
            )
        const captureSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)

        logic = incidentStatusLogic()
        logic.mount()

        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
        await expectLogic(logic).toFinishAllListeners()

        expect(statusPageRequestCount()).toBe(1)
        expect(captureSpy).toHaveBeenCalledTimes(1)
        expect(logic.values).toMatchObject({
            summary: null,
            rawStatus: 'operational',
            aiIncidentAlerts: [],
            statusDescription: null,
        })
    })
})
