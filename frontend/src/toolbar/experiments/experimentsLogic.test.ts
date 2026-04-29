import { getContext } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { experimentsLogic } from '~/toolbar/experiments/experimentsLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

const web_experiments = [
    { id: 1, name: 'Test Experiment 1', variants: { control: { transforms: [] } } },
    { id: 2, name: 'Test Experiment 2', variants: { control: { transforms: [] } } },
]

const buildResponse = ({
    ok = true,
    status = 200,
    body,
    nonJson = false,
}: {
    ok?: boolean
    status?: number
    body?: unknown
    nonJson?: boolean
}): Response =>
    ({
        ok,
        status,
        json: () => (nonJson ? Promise.reject(new Error('not json')) : Promise.resolve(body)),
        text: () => Promise.resolve(nonJson ? '<html>oops</html>' : JSON.stringify(body)),
    }) as any as Response

describe('toolbar experimentsLogic', () => {
    let logic: ReturnType<typeof experimentsLogic.build>
    let fetchMock: jest.Mock
    let dispatched: { type: string; payload: any }[]

    const mountAuthenticated = (): void => {
        toolbarConfigLogic.build({ apiURL: 'http://localhost', accessToken: 'test-token' }).mount()
        logic = experimentsLogic()
        logic.mount()
    }

    const mountUnauthenticated = (): void => {
        toolbarConfigLogic.build({ apiURL: 'http://localhost' }).mount()
        logic = experimentsLogic()
        logic.mount()
    }

    // Kea formats action types as "get experiments failure (logic.path)" — the camelCase
    // name is split on capitals and lowercased, then suffixed with the logic path in parens.
    const camelToSpaced = (s: string): string =>
        s
            .replace(/([A-Z])/g, ' $1')
            .toLowerCase()
            .trim()
    const findAction = (actionKey: string): { type: string; payload: any } | undefined =>
        dispatched.find((a) => a.type.startsWith(camelToSpaced(actionKey)))

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        fetchMock = jest.fn()
        // Default any unexpected fetch (e.g. uiHost reachability HEAD probe in afterMount)
        // to a benign 200 so tests don't blow up before they reach the assertions.
        fetchMock.mockResolvedValue(buildResponse({ ok: true, status: 200, body: {} }))
        global.fetch = fetchMock as unknown as typeof fetch

        // Capture every dispatched action so we can read the payload that kea-loaders
        // attaches to the auto-generated <action>Failure action.
        dispatched = []
        const store = getContext().store
        const origDispatch = store.dispatch
        store.dispatch = ((action: any) => {
            if (action && typeof action === 'object' && typeof action.type === 'string') {
                dispatched.push({ type: action.type, payload: action.payload })
            }
            return origDispatch(action)
        }) as typeof store.dispatch
    })

    it('loads experiments on success', async () => {
        fetchMock.mockResolvedValue(buildResponse({ ok: true, status: 200, body: { results: web_experiments } }))
        mountAuthenticated()
        await expectLogic(logic, () => logic.actions.getExperiments())
            .delay(0)
            .toMatchValues({ allExperiments: web_experiments, experimentCount: 2 })
    })

    it('returns empty list on no-token short-circuit (401 with results sentinel)', async () => {
        // With no accessToken, toolbarFetch returns a synthetic 401 with {results: []}
        // without hitting fetch — the loader should treat that as an empty list rather
        // than re-prompting auth on every mount.
        mountUnauthenticated()
        const authenticate = jest.spyOn(toolbarConfigLogic.findMounted()!.actions, 'authenticate')

        await expectLogic(logic, () => logic.actions.getExperiments())
            .delay(0)
            .toMatchValues({ allExperiments: [], experimentCount: 0 })

        expect(authenticate).not.toHaveBeenCalled()
        // toolbarFetch's no-token short-circuit must NOT make a real network call to the
        // experiments endpoint. Other fetches (e.g. uiHost reachability HEAD) may run.
        const experimentsCalls = fetchMock.mock.calls.filter(([url]) =>
            String(url).includes('/api/projects/@current/web_experiments/')
        )
        expect(experimentsCalls).toHaveLength(0)
    })

    it('triggers authenticate and returns empty list on real 401 with non-array body', async () => {
        fetchMock.mockResolvedValue(
            buildResponse({ ok: false, status: 401, body: { detail: 'Authentication credentials were not provided.' } })
        )
        mountAuthenticated()
        const authenticate = jest.spyOn(toolbarConfigLogic.findMounted()!.actions, 'authenticate')

        await expectLogic(logic, () => logic.actions.getExperiments())
            .delay(0)
            .toMatchValues({ allExperiments: [] })

        expect(authenticate).toHaveBeenCalledTimes(1)
    })

    it('triggers authenticate on 403', async () => {
        fetchMock.mockResolvedValue(buildResponse({ ok: false, status: 403, body: { detail: 'Forbidden' } }))
        mountAuthenticated()
        const authenticate = jest.spyOn(toolbarConfigLogic.findMounted()!.actions, 'authenticate')

        await expectLogic(logic, () => logic.actions.getExperiments())
            .delay(0)
            .toMatchValues({ allExperiments: [] })

        expect(authenticate).toHaveBeenCalledTimes(1)
    })

    it('throws an error including status, URL, and body snippet on 5xx', async () => {
        fetchMock.mockResolvedValue(buildResponse({ ok: false, status: 503, body: { detail: 'Service unavailable' } }))
        mountAuthenticated()

        await expectLogic(logic, () => logic.actions.getExperiments())
            .delay(0)
            .toDispatchActions(['getExperimentsFailure'])

        const failure = findAction('getExperimentsFailure')
        const message: string = failure?.payload?.error ?? ''
        expect(message).toContain('HTTP 503')
        expect(message).toContain('/api/projects/@current/web_experiments/')
        expect(message).toContain('Service unavailable')
    })

    it('throws diagnostic error on non-JSON body', async () => {
        fetchMock.mockResolvedValue(buildResponse({ ok: false, status: 502, nonJson: true }))
        mountAuthenticated()

        await expectLogic(logic, () => logic.actions.getExperiments())
            .delay(0)
            .toDispatchActions(['getExperimentsFailure'])

        const message: string = findAction('getExperimentsFailure')?.payload?.error ?? ''
        expect(message).toContain('HTTP 502')
        expect(message).toContain('<non-JSON body>')
    })

    it('throws diagnostic error on 200 with unexpected shape', async () => {
        fetchMock.mockResolvedValue(buildResponse({ ok: true, status: 200, body: { detail: 'oops' } }))
        mountAuthenticated()

        await expectLogic(logic, () => logic.actions.getExperiments())
            .delay(0)
            .toDispatchActions(['getExperimentsFailure'])

        const message: string = findAction('getExperimentsFailure')?.payload?.error ?? ''
        expect(message).toContain('unexpected response shape')
        expect(message).toContain('status 200')
        expect(message).toContain('"detail":"oops"')
    })
})
