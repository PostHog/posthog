import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { personPropertyMutationLogic } from './personPropertyMutationLogic'

const eventId = '0192a5c8-0000-0000-0000-000000000000'

describe('personPropertyMutationLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        { rows: [[JSON.stringify({ $set: { plan: 'pro' }, $set_once: { first: false }, $unset: ['trial'] })]] },
        { rows: [] },
    ])('loads the retained payload with one event lookup: $rows', async ({ rows }) => {
        let requests = 0
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as { query: { query: string } }
                    requests++
                    expect(body.query.query).toContain('posthog.person_property_mutation_log')
                    expect(body.query.query).toContain(eventId)
                    expect(body.query.query).not.toContain('JOIN')
                    return [200, { results: rows }]
                },
            },
        })
        const logic = personPropertyMutationLogic({ eventId })
        logic.mount()
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                mutations: rows.length ? JSON.parse(rows[0][0]) : {},
                mutationsLoading: false,
                mutationsFailed: false,
            })
        expect(requests).toBe(1)
        logic.unmount()
    })

    it('distinguishes a failed lookup from an empty log', async () => {
        useMocks({ post: { '/api/environments/:team_id/query/:kind': () => [500, {}] } })
        const logic = personPropertyMutationLogic({ eventId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            mutations: null,
            mutationsLoading: false,
            mutationsFailed: true,
        })
        logic.unmount()
    })
})
