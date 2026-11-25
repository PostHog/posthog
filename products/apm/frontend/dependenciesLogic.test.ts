import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { dependenciesLogic } from './dependenciesLogic'
import type { DependenciesResponseApi } from './generated/api.schemas'

const RESPONSE: DependenciesResponseApi = {
    edges: [
        { caller: 'web', callee: 'api', inferred: false, kind: 'service', requests: 10, error_count: 0, p95_ms: 5 },
    ],
    truncated: false,
    sampled: false,
    trace_count: 1,
    environment: null,
    service: null,
    date_from: '2026-06-02T08:00:00Z',
    date_to: '2026-06-02T09:00:00Z',
}
const TOO_MANY_SPANS = 'This window reads too many spans. Pick a shorter window or one service.'

describe('dependenciesLogic', () => {
    let logic: ReturnType<typeof dependenciesLogic.build>
    let requests: URLSearchParams[]
    let reply: [number, object]

    beforeEach(() => {
        requests = []
        reply = [200, RESPONSE]
        useMocks({
            get: {
                '/api/projects/:team_id/apm/services/': () => [200, { results: [], environments: [] }],
                '/api/projects/:team_id/apm/dependencies/': ({ request }) => {
                    requests.push(new URL(request.url).searchParams)
                    return reply
                },
            },
        })
        initKeaTests()
        logic = dependenciesLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['a validation error keeps its message', 400, { detail: TOO_MANY_SPANS }, TOO_MANY_SPANS],
        ['a server error has no message to show', 500, { detail: 'Server error' }, null],
    ])('%s', async (_name, status, body, detail) => {
        reply = [status, body]
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadDependenciesFailure'])
        expect(logic.values.dependenciesLoadError).toBe(true)
        expect(logic.values.dependenciesLoadErrorDetail).toBe(detail)
    })

    it('loads only the picked service after a window that was too heavy', async () => {
        reply = [400, { detail: TOO_MANY_SPANS }]
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadDependenciesFailure'])
        expect(requests[0].has('service')).toBe(false)

        reply = [200, { ...RESPONSE, service: 'api' }]
        logic.actions.setDependencyService('api')
        await expectLogic(logic).toDispatchActions(['loadDependenciesSuccess'])
        expect(requests[requests.length - 1].get('service')).toBe('api')
        expect(logic.values.dependenciesLoadErrorDetail).toBeNull()
    })
})
