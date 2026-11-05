import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { biWorksheetsLogic } from './biWorksheetsLogic'

describe('worksheet library', () => {
    const requests: URL[] = []
    beforeEach(() => {
        requests.length = 0
        useMocks({
            get: {
                '/api/projects/:team_id/insights/': ({ request }) => {
                    requests.push(new URL(request.url))
                    return [200, { count: 0, results: [] }]
                },
            },
        })
        initKeaTests()
    })

    it.each([
        ['/bi?open_insight=worksheet1', '/bi/worksheet1'],
        ['/bi#q=', '/bi/new'],
    ])('preserves legacy worksheet links: %s', async (url, path) => {
        router.actions.push(url)
        const logic = biWorksheetsLogic()
        logic.mount()
        try {
            await expectLogic(logic).toFinishAllListeners()
            expect(router.values.location.pathname).toBe(`/project/997${path}`)
            expect(logic.values.worksheets).toBeNull()
        } finally {
            logic.unmount()
        }
    })

    it.each(['createdBy', 'favorites'] as const)(
        'filters %s across all pages and clears the filter without losing search or recent mode',
        async (filter) => {
            const logic = biWorksheetsLogic()
            logic.mount()
            try {
                await expectLogic(logic).toFinishAllListeners()
                logic.actions.setSearch('revenue')
                logic.actions.setRecent(true)
                await expectLogic(logic).toFinishAllListeners()
                logic.actions.setPage(3)
                await expectLogic(logic).toFinishAllListeners()
                expect(requests.at(-1)?.searchParams.get('offset')).toBe('100')

                if (filter === 'createdBy') {
                    logic.actions.setCreatedBy([42, 43])
                } else {
                    logic.actions.setFavorited(true)
                }
                await expectLogic(logic).toFinishAllListeners()
                const params = requests.at(-1)!.searchParams
                expect(params.get('offset')).toBe('0')
                expect(params.get('search')).toBe('revenue')
                expect(params.get('insight')).toBe('BI')
                expect(params.get('order')).toBe('-last_viewed_at')
                expect(params.get(filter === 'createdBy' ? 'created_by' : 'favorited')).toBe(
                    filter === 'createdBy' ? '[42,43]' : 'true'
                )

                logic.actions.setCreatedBy([])
                logic.actions.setFavorited(false)
                await expectLogic(logic).toFinishAllListeners()
                expect(requests.at(-1)!.searchParams.has('created_by')).toBe(false)
                expect(requests.at(-1)!.searchParams.has('favorited')).toBe(false)
            } finally {
                logic.unmount()
            }
        }
    )
})
