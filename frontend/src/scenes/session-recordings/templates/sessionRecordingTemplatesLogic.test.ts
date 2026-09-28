import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ReplayTemplateType } from '~/types'

import { TEMPLATE_BASE_FILTERS, sessionReplayTemplatesLogic } from './sessionRecordingTemplatesLogic'

const template: ReplayTemplateType = {
    key: 'signup-flow',
    name: 'Signup flow',
    description: '',
    categories: ['B2B'],
    variables: [{ type: 'pageview', name: 'Signup page URL', key: 'signup-page-url' }],
}

describe('sessionReplayTemplatesLogic', () => {
    let logic: ReturnType<typeof sessionReplayTemplatesLogic.build>
    let recordingsRequests: string[]

    beforeEach(() => {
        recordingsRequests = []
        localStorage.clear()
        initKeaTests()
        logic = sessionReplayTemplatesLogic({ template, category: 'B2B' })
        logic.mount()
    })

    it.each([
        [3, false],
        [25, true],
    ])('counts %s matching recordings (has more: %s) once a variable is set', async (resultCount, hasNext) => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings': ({ request }) => {
                    recordingsRequests.push(new URL(request.url).search)
                    return [200, { results: Array(resultCount).fill({ id: 'r' }), has_next: hasNext }]
                },
            },
        })

        logic.actions.showVariables()
        await expectLogic(logic).toFinishAllListeners()
        expect(recordingsRequests).toHaveLength(0)

        logic.actions.setVariable({ ...template.variables![0], value: '/sign-up' })
        await expectLogic(logic).toFinishAllListeners()

        expect(recordingsRequests).toHaveLength(1)
        expect(recordingsRequests[0]).toContain('sign-up')
        expect(recordingsRequests[0]).toContain('filter_test_accounts=false')
        expect(logic.values.matchCount).toEqual({ count: resultCount, hasMore: hasNext })
    })

    it('applies the template with the same base filters the count uses', () => {
        logic.actions.setVariable({ ...template.variables![0], value: '/sign-up' })

        expect(logic.values.filtersToApply).toMatchObject(TEMPLATE_BASE_FILTERS)
        expect(logic.values.filtersToApply.filter_group).toBeTruthy()
    })

    it('counts once when a card opens, not on every click inside it', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings': ({ request }) => {
                    recordingsRequests.push(new URL(request.url).search)
                    return [200, { results: [], has_next: false }]
                },
            },
        })
        logic.actions.setVariable({ ...template.variables![0], value: '/sign-up' })
        logic.actions.showVariables()
        logic.actions.showVariables()
        await expectLogic(logic).toFinishAllListeners()

        expect(recordingsRequests).toHaveLength(1)
    })

    it('marks the count as failed instead of throwing when the request errors', async () => {
        useMocks({ get: { '/api/environments/:team_id/session_recordings': () => [500, { detail: 'boom' }] } })

        logic.actions.showVariables()
        logic.actions.setVariable({ ...template.variables![0], value: '/sign-up' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.matchCountError).toBe(true)
        expect(logic.values.matchCount).toBeNull()
    })
})
