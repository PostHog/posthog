import { expectLogic } from 'kea-test-utils'

import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { useMocks } from '~/mocks/jest'
import { MockSignature } from '~/mocks/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { PEOPLE_LIST_DEFAULT_QUERY, personsSceneLogic } from './personsSceneLogic'

const blankScene = (): any => ({ scene: { component: () => null, logic: null } })
const scenes: any = { [Scene.Persons]: blankScene }

describe('personsSceneLogic', () => {
    let logic: ReturnType<typeof personsSceneLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/persons/reset_person_distinct_id/': [200, {}],
            },
        })
        initKeaTests()
        sceneLogic({ scenes }).mount()
        sceneLogic.actions.setTabs([
            { id: '1', title: '...', pathname: '/', search: '', hash: '', active: true, iconType: 'blank' },
        ])
        logic = personsSceneLogic({ tabId: '1' })
        logic.mount()
    })

    describe('query reducer', () => {
        it('starts with default query', () => {
            expectLogic(logic).toMatchValues({
                query: PEOPLE_LIST_DEFAULT_QUERY,
            })
        })

        it('setQuery preserves defaultColumns even when custom query omits them', () => {
            const customQuery: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.ActorsQuery,
                    select: ['person', 'person.created_at'],
                },
                full: true,
            }

            logic.actions.setQuery(customQuery)

            expectLogic(logic).toMatchValues({
                query: expect.objectContaining({
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.ActorsQuery,
                        select: ['person', 'person.created_at'],
                    },
                    full: true,
                    defaultColumns: PEOPLE_LIST_DEFAULT_QUERY.defaultColumns,
                }),
            })
        })

        it('setQuery replaces previous query state', () => {
            const query1 = {
                ...PEOPLE_LIST_DEFAULT_QUERY,
                source: { ...PEOPLE_LIST_DEFAULT_QUERY.source, select: ['person'] },
            }
            const query2 = {
                ...PEOPLE_LIST_DEFAULT_QUERY,
                source: { ...PEOPLE_LIST_DEFAULT_QUERY.source, select: ['person', 'person.created_at'] },
            }

            logic.actions.setQuery(query1)
            logic.actions.setQuery(query2)

            expectLogic(logic).toMatchValues({
                query: expect.objectContaining({
                    source: expect.objectContaining({
                        select: ['person', 'person.created_at'],
                    }),
                }),
            })
        })
    })

    describe('boolean reducers', () => {
        it.each([
            { action: 'setShowDisplayNameNudge', field: 'showDisplayNameNudge' },
            { action: 'setIsBannerLoading', field: 'isBannerLoading' },
        ])('$field starts false and toggles via $action', ({ action, field }) => {
            expectLogic(logic).toMatchValues({ [field]: false })

            const act = logic.actions[action as 'setShowDisplayNameNudge' | 'setIsBannerLoading']

            act(true)
            expectLogic(logic).toMatchValues({ [field]: true })

            act(false)
            expectLogic(logic).toMatchValues({ [field]: false })
        })
    })

    describe('resetDeletedDistinctId listener', () => {
        it('calls the API to reset a distinct ID', async () => {
            const spy: MockSignature = jest.fn(() => [200, {}])
            useMocks({
                post: {
                    '/api/environments/:team_id/persons/reset_person_distinct_id/': spy,
                },
            })

            await expectLogic(logic, () => {
                logic.actions.resetDeletedDistinctId('some-distinct-id')
            }).toFinishAllListeners()

            expect(spy).toHaveBeenCalledTimes(1)
        })
    })
})
