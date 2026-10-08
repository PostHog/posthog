import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { actionEventHealthLogic } from './actionEventHealthLogic'

describe('actionEventHealthLogic', () => {
    let logic: ReturnType<typeof actionEventHealthLogic.build>
    let requestedSearches: URLSearchParams[]

    beforeEach(() => {
        requestedSearches = []

        useMocks({
            get: {
                '/api/projects/:team/event_definitions/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requestedSearches.push(params)
                    const names = params.getAll('names')
                    const results = [
                        { id: '1', name: 'fresh_event', last_seen_at: dayjs().subtract(1, 'hour').toISOString() },
                        { id: '2', name: 'stale_event', last_seen_at: dayjs().subtract(90, 'day').toISOString() },
                        { id: '3', name: 'constructor', last_seen_at: dayjs().subtract(1, 'hour').toISOString() },
                        { id: '4', name: '__proto__', last_seen_at: dayjs().subtract(1, 'hour').toISOString() },
                    ].filter((definition) => names.includes(definition.name))
                    return [200, { count: results.length, results }]
                },
            },
        })

        initKeaTests()
        logic = actionEventHealthLogic()
        logic.mount()
    })

    // The whole point of the warning: an event nobody sends any more, and an event with no
    // definition at all, are both actions that silently match nothing.
    it.each([
        ['fresh_event', undefined],
        ['stale_event', 'stale'],
        ['deleted_event', 'missing'],
    ])('reports %s as %s', async (event, status) => {
        logic.actions.requestEventNames([event])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.eventHealthIssues[event]?.status).toEqual(status)
    })

    // A page of actions asks row by row. Without batching that is one request per row.
    it('asks for a burst of event names in a single request', async () => {
        logic.actions.requestEventNames(['fresh_event'])
        logic.actions.requestEventNames(['stale_event'])
        logic.actions.requestEventNames([null, undefined])
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedSearches).toHaveLength(1)
        expect(requestedSearches[0].getAll('names')).toEqual(['fresh_event', 'stale_event'])
    })

    // A page of many actions, or of long event names, used to go out as one oversized URL that a
    // proxy rejects whole. Nothing wrote to `definitions` on failure, so every tag on the page
    // stayed absent and the same URL went out again on the next burst.
    it('splits a burst too long for one URL across requests', async () => {
        const names = Array.from({ length: 40 }, (_, index) => `event_${index}_${'x'.repeat(100)}`)

        logic.actions.requestEventNames(names)
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedSearches.length).toBeGreaterThan(1)
        for (const search of requestedSearches) {
            expect(search.toString().length).toBeLessThan(4000)
        }
        expect(requestedSearches.flatMap((search) => search.getAll('names'))).toEqual(names)
    })

    it('does not ask again for an event it already resolved', async () => {
        logic.actions.requestEventNames(['fresh_event'])
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.requestEventNames(['fresh_event'])
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedSearches).toHaveLength(1)
    })

    // The endpoint splits each `names` value on commas, so it answers about `purchase` and
    // `completed` instead. The full name then looks like it has no definition, which drew a
    // "Not seen" tag on a step that matches fine.
    it('stays quiet about an event name containing a comma', async () => {
        logic.actions.requestEventNames(['purchase,completed'])
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedSearches).toHaveLength(0)
        expect(logic.values.eventHealthIssues['purchase,completed']).toBeUndefined()
    })

    // Held through a normal object these names read as already resolved, so the request never went
    // out, and the health map handed back a value off Object.prototype. Both drew a "Not seen" tag
    // on a healthy event.
    it.each(['constructor', '__proto__'])('treats %s as an ordinary event name', async (event) => {
        logic.actions.requestEventNames([event])
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedSearches[0]?.getAll('names')).toEqual([event])
        expect(logic.values.eventHealthIssues[event]).toBeUndefined()
    })
})
