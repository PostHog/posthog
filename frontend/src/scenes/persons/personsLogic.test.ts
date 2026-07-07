import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { MockSignature } from '~/mocks/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PersonsTabType, PersonType, PropertyFilterType, PropertyOperator } from '~/types'

import { personsLogic } from './personsLogic'

describe('personsLogic', () => {
    afterEach(resumeKeaLoadersErrors)
    let logic: ReturnType<typeof personsLogic.build>

    const mockPersonsApiHandler: MockSignature = ({ request }) => {
        const url = new URL(request.url)
        if (['+', 'abc', 'xyz'].includes(url.searchParams.get('distinct_id') ?? '')) {
            return [200, { results: ['person from api'] }]
        }
        if (['test@test.com'].includes(url.searchParams.get('distinct_id') ?? '')) {
            return [
                200,
                {
                    results: [
                        {
                            id: 1,
                            name: 'test@test.com',
                            distinct_ids: ['test@test.com'],
                            uuid: 'abc-123',
                        },
                    ],
                },
            ]
        }
        return [200, { result: ['result from api'] }]
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/persons/': mockPersonsApiHandler,
            },
        })
        initKeaTests()
        logic = personsLogic({ syncWithUrl: true })
        logic.mount()
    })

    describe('syncs with insightLogic', () => {
        it('setAllFilters properties works', async () => {
            router.actions.push('/persons')
            await expectLogic(logic, () => {
                logic.actions.setListFilters({
                    properties: [{ key: 'email', operator: PropertyOperator.IsSet, type: PropertyFilterType.Person }],
                })
                logic.actions.loadPersons()
            })
                .toMatchValues(logic, {
                    listFilters: { properties: [{ key: 'email', operator: 'is_set', type: 'person' }] },
                })
                .toDispatchActions(router, ['replace', 'locationChanged'])
                .toMatchValues(router, {
                    searchParams: { properties: [{ key: 'email', operator: 'is_set', type: 'person' }] },
                })
        })
    })

    describe('loads a person', () => {
        it('starts with a null person', async () => {
            await expectLogic(logic).toMatchValues({
                person: null,
            })
        })

        it('gets the person from the url', async () => {
            router.actions.push('/person/test%40test.com')

            await expectLogic(logic)
                .toDispatchActions(['loadPerson', 'loadPersonSuccess'])
                .toMatchValues({
                    person: {
                        id: 1,
                        name: 'test@test.com',
                        distinct_ids: ['test@test.com'],
                        uuid: 'abc-123',
                    },
                })

            // Dont fetch again if the url changes (even with encoded distinct IDs)
            router.actions.push('/person/test%40test.com', {}, { sessionRecordingId: 'abc-123' })
            await expectLogic(logic).toNotHaveDispatchedActions(['loadPerson'])
        })

        it('loads a person', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPerson('abc')
            })
                .toDispatchActions(['loadPerson', 'loadPersonSuccess'])
                .toMatchValues({
                    person: 'person from api',
                })
        })

        it('loads a person where id includes +', async () => {
            jest.spyOn(api, 'get')
            await expectLogic(logic, () => {
                logic.actions.loadPerson('+')
                // has encoded from + in the action to %2B in the API call
                expect(api.get).toHaveBeenCalledWith(
                    `api/environments/${MOCK_TEAM_ID}/persons?distinct_id=%2B`,
                    undefined
                )
            })
                .toDispatchActions(['loadPerson', 'loadPersonSuccess'])
                .toMatchValues({
                    person: 'person from api',
                })
        })

        it('clears the person when switching between people', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPerson('abc')
            })
                .toDispatchActions(['loadPersonSuccess'])
                .toMatchValues({
                    person: 'person from api',
                })

            await expectLogic(logic, () => {
                logic.actions.loadPerson('xyz')
            })
                .toMatchValues({
                    person: null,
                })
                .toDispatchActions(['loadPersonSuccess'])
                .toMatchValues({
                    person: 'person from api',
                })
        })
    })

    describe('loadPersonUUID error handling', () => {
        it('surfaces a genuine load failure as personError', async () => {
            silenceKeaLoadersErrors()
            jest.spyOn(api, 'query').mockRejectedValueOnce(new Error('boom'))

            await expectLogic(logic, () => {
                logic.actions.loadPersonUUID('some-uuid')
            })
                .toDispatchActions(['loadPersonUUID', 'loadPersonUUIDFailure'])
                .toMatchValues({
                    person: null,
                    personError: 'boom',
                })
        })

        it('swallows an aborted query without surfacing an error', async () => {
            const abortError = new Error('aborted')
            abortError.name = 'AbortError'
            jest.spyOn(api, 'query').mockRejectedValueOnce(abortError)

            await expectLogic(logic, () => {
                logic.actions.loadPersonUUID('some-uuid')
            })
                .toDispatchActions(['loadPersonUUID', 'loadPersonUUIDSuccess'])
                .toNotHaveDispatchedActions(['loadPersonUUIDFailure'])
                .toMatchValues({
                    person: null,
                    personError: null,
                })
        })

        it('keeps the already-loaded person when an in-flight query is aborted', async () => {
            const existingPerson: PersonType = {
                id: 'person-1',
                uuid: 'uuid-1',
                distinct_ids: ['some-uuid'],
                properties: {},
                is_identified: true,
                created_at: '2024-01-01',
            }
            logic.actions.setPerson(existingPerson)

            const abortError = new Error('aborted')
            abortError.name = 'AbortError'
            jest.spyOn(api, 'query').mockRejectedValueOnce(abortError)

            await expectLogic(logic, () => {
                logic.actions.loadPersonUUID('some-uuid')
            })
                .toDispatchActions(['loadPersonUUID', 'loadPersonUUIDSuccess'])
                .toNotHaveDispatchedActions(['loadPersonUUIDFailure'])
                .toMatchValues({
                    person: existingPerson,
                    personError: null,
                })
        })
    })

    describe('Load cohorts', () => {
        it("Doesn't load cohort if we're on", async () => {
            await expectLogic(logic, () => {
                logic.actions.loadCohorts()
            }).toMatchValues({ cohorts: null })
        })
    })

    describe('editProperty', () => {
        const person: PersonType = {
            id: 'person-1',
            uuid: 'uuid-1',
            distinct_ids: ['did-1'],
            properties: { existing: 'value' },
            is_identified: true,
            created_at: '2024-01-01',
        }

        beforeEach(() => {
            logic.actions.setPerson(person)
        })

        it('updates existing property immutably', async () => {
            useMocks({
                get: { '/api/environments/:team_id/persons/': mockPersonsApiHandler },
                post: { '/api/environments/:team_id/persons/:id/update_property/': [200, {}] },
            })

            const originalProperties = logic.values.person!.properties

            await expectLogic(logic, () => {
                logic.actions.editProperty('existing', 'new-value')
            }).toFinishAllListeners()

            expect(logic.values.person!.properties).toEqual({ existing: 'new-value' })
            // The original properties object must not have been mutated
            expect(originalProperties).toEqual({ existing: 'value' })
        })

        it('adds new property at the top', async () => {
            useMocks({
                get: { '/api/environments/:team_id/persons/': mockPersonsApiHandler },
                post: { '/api/environments/:team_id/persons/:id/update_property/': [200, {}] },
            })

            await expectLogic(logic, () => {
                logic.actions.editProperty('newKey', 'newVal')
            }).toFinishAllListeners()

            const keys = Object.keys(logic.values.person!.properties)
            expect(keys[0]).toBe('newKey')
            expect(logic.values.person!.properties).toEqual({ newKey: 'newVal', existing: 'value' })
        })

        it('rolls back on API failure', async () => {
            useMocks({
                get: { '/api/environments/:team_id/persons/': mockPersonsApiHandler },
                post: { '/api/environments/:team_id/persons/:id/update_property/': () => [500, {}] },
            })

            await expectLogic(logic, () => {
                logic.actions.editProperty('existing', 'will-fail')
            }).toFinishAllListeners()

            expect(logic.values.person!.properties).toEqual({ existing: 'value' })
        })

        it('coerces values via coercePropertyValue', async () => {
            useMocks({
                get: { '/api/environments/:team_id/persons/': mockPersonsApiHandler },
                post: { '/api/environments/:team_id/persons/:id/update_property/': [200, {}] },
            })

            await expectLogic(logic, () => {
                logic.actions.editProperty('existing', '42')
            }).toFinishAllListeners()

            expect(logic.values.person!.properties.existing).toBe(42)
        })
    })

    describe('deleteProperty', () => {
        const person: PersonType = {
            id: 'person-1',
            uuid: 'uuid-1',
            distinct_ids: ['did-1'],
            properties: { keep: 'yes', remove: 'me' },
            is_identified: true,
            created_at: '2024-01-01',
        }

        beforeEach(() => {
            logic.actions.setPerson(person)
        })

        it('removes the property from person', async () => {
            useMocks({
                get: { '/api/environments/:team_id/persons/': mockPersonsApiHandler },
                post: { '/api/environments/:team_id/persons/:id/delete_property/': [200, {}] },
            })

            await expectLogic(logic, () => {
                logic.actions.deleteProperty('remove')
            }).toFinishAllListeners()

            expect(logic.values.person!.properties).toEqual({ keep: 'yes' })
        })

        it('rolls back on API failure', async () => {
            useMocks({
                get: { '/api/environments/:team_id/persons/': mockPersonsApiHandler },
                post: { '/api/environments/:team_id/persons/:id/delete_property/': () => [500, {}] },
            })

            await expectLogic(logic, () => {
                logic.actions.deleteProperty('remove')
            }).toFinishAllListeners()

            expect(logic.values.person!.properties).toEqual({ keep: 'yes', remove: 'me' })
        })
    })

    describe('listFilters reducer', () => {
        it('removes empty properties array', async () => {
            await expectLogic(logic, () => {
                logic.actions.setListFilters({ properties: [] })
            }).toMatchValues({
                listFilters: {},
            })
        })

        it('filters out invalid property filters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setListFilters({
                    properties: [
                        { key: 'email', operator: PropertyOperator.IsSet, type: PropertyFilterType.Person },
                        {} as any,
                    ],
                })
            }).toMatchValues({
                listFilters: {
                    properties: [{ key: 'email', operator: PropertyOperator.IsSet, type: PropertyFilterType.Person }],
                },
            })
        })

        it('merges with existing filters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setListFilters({ search: 'alice' })
            }).toMatchValues({
                listFilters: { search: 'alice' },
            })

            await expectLogic(logic, () => {
                logic.actions.setListFilters({
                    properties: [{ key: 'name', operator: PropertyOperator.IsSet, type: PropertyFilterType.Person }],
                })
            }).toMatchValues({
                listFilters: {
                    search: 'alice',
                    properties: [{ key: 'name', operator: PropertyOperator.IsSet, type: PropertyFilterType.Person }],
                },
            })
        })
    })

    describe('setPerson / setPersons reducers', () => {
        const personA: PersonType = {
            id: '1',
            uuid: 'uuid-1',
            distinct_ids: ['a'],
            properties: { name: 'Alice' },
            is_identified: true,
            created_at: '2024-01-01',
        }
        const personB: PersonType = {
            id: '2',
            uuid: 'uuid-2',
            distinct_ids: ['b'],
            properties: { name: 'Bob' },
            is_identified: true,
            created_at: '2024-01-02',
        }

        it('setPerson updates matching person in the list', async () => {
            await expectLogic(logic, () => {
                logic.actions.setPersons([personA, personB])
            }).toMatchValues({
                persons: expect.objectContaining({
                    results: expect.arrayContaining([
                        expect.objectContaining({ id: '1' }),
                        expect.objectContaining({ id: '2' }),
                    ]),
                }),
            })

            const updatedA = { ...personA, properties: { name: 'Alice Updated' } }
            await expectLogic(logic, () => {
                logic.actions.setPerson(updatedA)
            }).toMatchValues({
                persons: expect.objectContaining({
                    results: expect.arrayContaining([
                        expect.objectContaining({ properties: { name: 'Alice Updated' } }),
                        expect.objectContaining({ id: '2' }),
                    ]),
                }),
            })
        })

        it('setPersons prepends to the results list', async () => {
            await expectLogic(logic, () => {
                logic.actions.setPersons([personA])
            }).toMatchValues({
                persons: expect.objectContaining({
                    results: [expect.objectContaining({ id: '1' })],
                }),
            })

            await expectLogic(logic, () => {
                logic.actions.setPersons([personB])
            }).toMatchValues({
                persons: expect.objectContaining({
                    results: [expect.objectContaining({ id: '2' }), expect.objectContaining({ id: '1' })],
                }),
            })
        })
    })

    describe('primaryDistinctId selector', () => {
        it.each([
            {
                name: 'prefers email over anon ID',
                distinctIds: ['03b16e4c0b14ef-00000000000000-1633685d-13c680-17878af3ba9d1c', 'alice@example.com'],
                expected: 'alice@example.com',
            },
            {
                name: 'prefers email over custom ID',
                distinctIds: [
                    '03b16e4c0b14ef-00000000000000-1633685d-13c680-17878af3ba9d1c',
                    'user123',
                    'alice@example.com',
                ],
                expected: 'alice@example.com',
            },
            {
                name: 'prefers custom ID over anon ID',
                distinctIds: ['03b16e4c0b14ef-00000000000000-1633685d-13c680-17878af3ba9d1c', 'user123'],
                expected: 'user123',
            },
            {
                name: 'falls back to first when all score equally',
                distinctIds: ['550e8400-e29b-41d4-a716-446655440000', 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'],
                expected: '550e8400-e29b-41d4-a716-446655440000',
            },
            {
                name: 'returns null when person has no distinct IDs',
                distinctIds: [],
                expected: null,
            },
        ])('$name', async ({ distinctIds, expected }) => {
            const person: PersonType = {
                id: '1',
                uuid: 'uuid-1',
                distinct_ids: distinctIds,
                properties: {},
                is_identified: true,
                created_at: '2024-01-01',
            }

            await expectLogic(logic, () => {
                logic.actions.setPerson(person)
            }).toMatchValues({
                primaryDistinctId: expected,
            })
        })

        it('returns null when person is null', async () => {
            await expectLogic(logic).toMatchValues({
                primaryDistinctId: null,
            })
        })
    })

    describe('tab navigation', () => {
        it('navigateToTab updates activeTab', async () => {
            await expectLogic(logic, () => {
                logic.actions.navigateToTab(PersonsTabType.EVENTS)
            }).toMatchValues({
                activeTab: PersonsTabType.EVENTS,
            })
        })

        it('setActiveTab updates activeTab', async () => {
            await expectLogic(logic, () => {
                logic.actions.setActiveTab(PersonsTabType.COHORTS)
            }).toMatchValues({
                activeTab: PersonsTabType.COHORTS,
            })
        })

        it('currentTab falls back to defaultTab when activeTab is null', async () => {
            await expectLogic(logic).toMatchValues({
                activeTab: null,
                currentTab: logic.values.defaultTab,
            })
        })

        it('currentTab uses activeTab when set', async () => {
            await expectLogic(logic, () => {
                logic.actions.setActiveTab(PersonsTabType.EVENTS)
            }).toMatchValues({
                currentTab: PersonsTabType.EVENTS,
            })
        })
    })

    describe('resetEventsQuery', () => {
        const person: PersonType = {
            id: 'person-1',
            uuid: 'uuid-1',
            distinct_ids: ['did-1'],
            properties: {},
            is_identified: true,
            created_at: '2024-01-01',
        }

        beforeEach(async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/persons/': () => [200, { results: [person] }],
                },
            })
            await expectLogic(logic, () => {
                logic.actions.loadPerson('did-1')
            }).toDispatchActions(['loadPerson', 'loadPersonSuccess'])
        })

        it('eventsQueryIsDirty is false right after the person loads', async () => {
            await expectLogic(logic).toMatchValues({ eventsQueryIsDirty: false })
        })

        it('eventsQueryIsDirty becomes true after modifying filters', async () => {
            const current = logic.values.eventsQuery!
            logic.actions.setEventsQuery({
                ...current,
                source: { ...current.source, events: ['$pageview'] } as any,
            } as DataTableNode)

            await expectLogic(logic).toMatchValues({ eventsQueryIsDirty: true })
        })

        it('resetEventsQuery restores the initial query', async () => {
            const current = logic.values.eventsQuery!
            logic.actions.setEventsQuery({
                ...current,
                source: { ...current.source, events: ['$pageview'], after: '-7d' } as any,
            } as DataTableNode)

            await expectLogic(logic).toMatchValues({ eventsQueryIsDirty: true })

            await expectLogic(logic, () => {
                logic.actions.resetEventsQuery()
            })
                .toDispatchActions(['resetEventsQuery', 'setEventsQuery'])
                .toMatchValues({ eventsQueryIsDirty: false })

            const resetSource = logic.values.eventsQuery?.source as any
            expect(resetSource).toMatchObject({
                kind: NodeKind.EventsQuery,
                personId: 'person-1',
                after: '-24h',
            })
            expect(resetSource.events).toBeUndefined()
        })
    })
})
