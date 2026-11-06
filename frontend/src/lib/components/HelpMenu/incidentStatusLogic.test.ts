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

    const outageInUs = {
        name: 'Outage',
        last_update_message: 'Investigating',
        current_worst_impact: 'partial_outage',
        affected_components: [{ name: 'API', group_name: '🇺🇸 US Cloud', current_status: 'partial_outage' }],
    }

    it.each([
        ['a well-formed body', { ongoing_incidents: [outageInUs], in_progress_maintenances: [] }, 'partial_outage'],
        ['a body without the incident arrays', { page_title: 'PostHog' }, 'operational'],
        [
            'an incident that has no affected components',
            { ongoing_incidents: [{ name: 'Outage' }], in_progress_maintenances: [] },
            'operational',
        ],
        [
            'a maintenance that has a non-object component',
            { ongoing_incidents: [], in_progress_maintenances: [{ name: 'Upgrade', affected_components: [null] }] },
            'operational',
        ],
        [
            'a component whose group name is not a string',
            {
                ongoing_incidents: [{ ...outageInUs, affected_components: [{ name: 'API', group_name: 7 }] }],
                in_progress_maintenances: [],
            },
            'operational',
        ],
    ])('resolves the status from %s', async (_name, body, expectedStatus) => {
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

        const malformed = expectedStatus === 'operational'
        expect(statusPageRequestCount()).toBe(1)
        expect(captureSpy).toHaveBeenCalledTimes(malformed ? 1 : 0)
        expect(logic.values.summary === null).toBe(malformed)
        expect(logic.values.rawStatus).toBe(expectedStatus)
    })
})
