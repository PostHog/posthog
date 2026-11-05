import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { addToCollectionLogic } from './addToCollectionLogic'
import { resetAnalyticsFeedSnapshot } from './analyticsFeedLogic'

const OTHER_USER = { ...MOCK_DEFAULT_USER, id: 999, uuid: 'other-user' }
const MINE = { id: 'fs-mine', ref: 'mine', path: 'Unfiled/Insights/Weekly\\/active', creator: MOCK_DEFAULT_USER.id }
const THEIRS = { id: 'fs-theirs', ref: 'theirs', path: 'Unfiled/Insights/Churn', creator: OTHER_USER.id }
const ALREADY_HERE = { id: 'fs-here', ref: 'here', path: 'Finance/Revenue', creator: OTHER_USER.id }

describe('addToCollectionLogic', () => {
    let moves: string[]

    beforeEach(() => {
        moves = []
        resetAnalyticsFeedSnapshot()
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    if (params.get('type__startswith') !== 'insight') {
                        return { results: [], next: null }
                    }
                    const rows = params.get('search')?.includes('user:me') ? [MINE] : [MINE, THEIRS, ALREADY_HERE]
                    return {
                        results: rows.map(({ creator, ...row }) => ({
                            ...row,
                            type: 'insight/trends',
                            href: `/insights/${row.ref}`,
                            meta: { created_by: creator },
                            created_at: '2026-01-01T00:00:00Z',
                        })),
                        users: [MOCK_DEFAULT_USER, OTHER_USER],
                        next: null,
                    }
                },
            },
            post: {
                '/api/projects/:team_id/file_system/:id/move/': async ({ params, request }) => {
                    const body = (await request.json()) as { new_path: string }
                    if (params.id === THEIRS.id) {
                        return [403, { detail: 'You do not have access to move this.' }]
                    }
                    moves.push(`${params.id} -> ${body.new_path}`)
                    return { id: params.id, path: body.new_path }
                },
            },
        })
        initKeaTests()
        userLogic.mount()
    })

    it('lists the person’s own work apart from everyone’s, and keeps a failed item selected after adding', async () => {
        const logic = addToCollectionLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.openAddToCollection('Finance')).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ feed: expect.objectContaining({ initialized: true }) })
        expect(logic.values.feed.items.map((item) => item.id)).toEqual(['mine'])
        logic.actions.toggleItem(logic.values.feed.items[0])

        await expectLogic(logic, () => logic.actions.setTab('all')).toFinishAllListeners()
        expect(logic.values.feed.items.map((item) => item.id)).toEqual(['mine', 'theirs', 'here'])
        logic.actions.toggleItem(logic.values.feed.items[1])

        await expectLogic(logic, () => logic.actions.addSelected()).toDispatchActions(['addFinished', 'itemsAdded'])

        expect(moves).toEqual(['fs-mine -> Finance/Weekly\\/active'])
        expect(Object.keys(logic.values.selected)).toEqual(['insight:theirs'])
        expect(logic.values.folder).toBe('Finance')
    })
})
