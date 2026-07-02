import { expectLogic } from 'kea-test-utils'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

import { experimentsLogic } from './experimentsLogic'

const web_experiments = [{ id: 1, name: 'Test Experiment 1', variants: {} }]

function mockFetch(response: Partial<Response> & { json?: () => Promise<unknown> }): void {
    global.fetch = jest.fn(() => Promise.resolve(response as Response))
}

describe('experimentsLogic', () => {
    let logic: ReturnType<typeof experimentsLogic.build>
    const savedFetch = global.fetch

    afterAll(() => {
        global.fetch = savedFetch
    })

    function mountLogic({ withToken = true }: { withToken?: boolean } = {}): void {
        initKeaTests()
        toolbarConfigLogic
            .build({ apiURL: 'http://localhost', ...(withToken ? { accessToken: 'test-token' } : {}) })
            .mount()
        logic = experimentsLogic()
        logic.mount()
    }

    it('loads experiments on a successful response', async () => {
        mockFetch({ ok: true, status: 200, json: () => Promise.resolve({ results: web_experiments }) })
        mountLogic()

        await expectLogic(logic, () => {
            logic.actions.getExperiments()
        })
            .toDispatchActions(['getExperiments', 'getExperimentsSuccess'])
            .toMatchValues({ allExperiments: web_experiments })
    })

    it('returns an empty list when unauthenticated (stubbed 401)', async () => {
        // No access token → toolbarFetch short-circuits to a stubbed 401, never hitting fetch.
        mountLogic({ withToken: false })

        await expectLogic(logic, () => {
            logic.actions.getExperiments()
        })
            .toDispatchActions(['getExperiments', 'getExperimentsSuccess'])
            .toMatchValues({ allExperiments: [] })
    })

    it('soft-fails to an empty list on a 5xx server error', async () => {
        mockFetch({ ok: false, status: 503, json: () => Promise.reject(new Error('unused')) })
        mountLogic()

        await expectLogic(logic, () => {
            logic.actions.getExperiments()
        })
            .toDispatchActions(['getExperiments', 'getExperimentsSuccess'])
            .toMatchValues({ allExperiments: [] })
    })

    it.each([
        ['a non-2xx response', { ok: false, status: 404, json: () => Promise.resolve({}) }],
        [
            'the body is not valid JSON',
            { ok: true, status: 200, json: () => Promise.reject(new Error('Unexpected token')) },
        ],
        [
            'results is not an array',
            { ok: true, status: 200, json: () => Promise.resolve({ results: { unexpected: true } }) },
        ],
    ] as [string, Partial<Response> & { json?: () => Promise<unknown> }][])(
        'soft-fails to an empty list when %s',
        async (_name, fetchResponse) => {
            mockFetch(fetchResponse)
            mountLogic()

            await expectLogic(logic, () => {
                logic.actions.getExperiments()
            })
                .toDispatchActions(['getExperiments', 'getExperimentsSuccess'])
                .toMatchValues({ allExperiments: [] })
        }
    )
})
