import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { MockSignature } from '~/mocks/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { PEOPLE_LIST_DEFAULT_QUERY, isPeopleListDefaultQuerySource, personsSceneLogic } from './personsSceneLogic'

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
        logic = personsSceneLogic()
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

    describe('isPeopleListDefaultQuerySource', () => {
        it.each([true, false])(
            'recognizes the team default query source when person_last_seen_at_enabled is %s',
            (enabled) => {
                teamLogic.actions.loadCurrentTeamSuccess({
                    ...MOCK_DEFAULT_TEAM,
                    extra_settings: { person_last_seen_at_enabled: enabled },
                })

                // The default columns depend on this setting. A saved table view must still restore
                // for teams that turned it on. The old static-constant check missed that case.
                expect(isPeopleListDefaultQuerySource(logic.values.defaultQuery.source)).toBe(true)
            }
        )

        it('rejects a query source with custom columns', () => {
            const source = { ...PEOPLE_LIST_DEFAULT_QUERY.source, select: ['person', 'pdi.distinct_id'] }
            expect(isPeopleListDefaultQuerySource(source)).toBe(false)
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
