import * as libUtils from 'lib/utils'
import {
    singleFilterToGroupFilter,
    splitGroupFilterToLocalFilters,
    toLocalFilters,
} from 'scenes/insights/filters/ActionFilter/entityFilterLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { EntityTypes, FilterLogicalOperator } from '~/types'

describe('ActionFilterGroup - Combining and Splitting Events', () => {
    beforeEach(() => {
        ;(libUtils as any).uuid = jest.fn().mockReturnValue('test-uuid')
        useMocks({
            get: {
                '/api/projects/:team/actions/': {
                    results: [],
                },
                '/api/projects/:team/event_definitions/': {
                    results: [],
                },
            },
        })
        initKeaTests()
    })

    describe('singleFilterToGroupFilter', () => {
        it('converts a single event filter to a group filter', () => {
            const eventFilter = {
                id: '$pageview',
                type: EntityTypes.EVENTS,
                name: '$pageview',
                order: 0,
                uuid: 'uuid-1',
            }

            const groupFilter = singleFilterToGroupFilter(eventFilter)

            expect(groupFilter).toMatchObject({
                id: null,
                type: EntityTypes.GROUPS,
                operator: FilterLogicalOperator.Or,
                order: 0,
                uuid: 'test-uuid',
            })
            expect(groupFilter.nestedFilters).not.toBeUndefined()
            expect(groupFilter.nestedFilters!).toHaveLength(1)
            expect(groupFilter.nestedFilters![0]).toEqual(eventFilter)
        })

        it('preserves math properties at group level', () => {
            const eventFilter = {
                id: '$pageview',
                type: EntityTypes.EVENTS,
                name: '$pageview',
                order: 0,
                math: 'dau',
                math_property: 'some_prop',
                uuid: 'uuid-1',
            }

            const groupFilter = singleFilterToGroupFilter(eventFilter)

            expect(groupFilter).toMatchObject({
                math: 'dau',
                math_property: 'some_prop',
            })
        })

        it('handles action filters', () => {
            const actionFilter = {
                id: '123',
                type: EntityTypes.ACTIONS,
                name: 'User Signup',
                order: 0,
                uuid: 'uuid-1',
            }

            const groupFilter = singleFilterToGroupFilter(actionFilter)

            expect(groupFilter.type).toBe(EntityTypes.GROUPS)
            expect(groupFilter.nestedFilters).toContainEqual(actionFilter)
        })
    })

    describe('splitGroupFilterToLocalFilters', () => {
        it('expands a group filter with two events back to individual filters', () => {
            const pageviewFilter = {
                id: '$pageview',
                type: EntityTypes.EVENTS,
                name: '$pageview',
                order: 0,
                uuid: 'uuid-1',
            }

            const exceptionFilter = {
                id: '$exception',
                type: EntityTypes.EVENTS,
                name: '$exception',
                order: 1,
                uuid: 'uuid-2',
            }

            const groupFilter = {
                id: null,
                type: EntityTypes.GROUPS,
                name: 'group',
                order: 0,
                operator: FilterLogicalOperator.Or,
                uuid: 'group-uuid',
                nestedFilters: [pageviewFilter, exceptionFilter],
            }

            const split = splitGroupFilterToLocalFilters(groupFilter, 0)

            expect(split).toHaveLength(2)
            expect(split[0]).toEqual(
                expect.objectContaining({
                    id: '$pageview',
                    order: 0,
                })
            )
            expect(split[1]).toEqual(
                expect.objectContaining({
                    id: '$exception',
                    order: 1,
                })
            )
        })

        it('maintains correct ordering when splitting', () => {
            const filter1 = {
                id: '$pageview',
                type: EntityTypes.EVENTS,
                name: '$pageview',
                order: 0,
                uuid: 'uuid-1',
            }

            const filter2 = {
                id: '$exception',
                type: EntityTypes.EVENTS,
                name: '$exception',
                order: 1,
                uuid: 'uuid-2',
            }

            const filter3 = {
                id: '$pageleave',
                type: EntityTypes.EVENTS,
                name: '$pageleave',
                order: 2,
                uuid: 'uuid-3',
            }

            const groupFilter = {
                id: null,
                type: EntityTypes.GROUPS,
                name: 'group',
                order: 0,
                operator: FilterLogicalOperator.Or,
                uuid: 'group-uuid',
                nestedFilters: [filter1, filter2, filter3],
            }

            const split = splitGroupFilterToLocalFilters(groupFilter, 5)

            expect(split).toHaveLength(3)
            expect(split[0].order).toBe(5)
            expect(split[1].order).toBe(6)
            expect(split[2].order).toBe(7)
        })

        it('handles groups with mix of events and actions', () => {
            const eventFilter = {
                id: '$pageview',
                type: EntityTypes.EVENTS,
                name: '$pageview',
                order: 0,
                uuid: 'uuid-1',
            }

            const actionFilter = {
                id: '123',
                type: EntityTypes.ACTIONS,
                name: 'User Signup',
                order: 1,
                uuid: 'uuid-2',
            }

            const groupFilter = {
                id: null,
                type: EntityTypes.GROUPS,
                name: 'group',
                order: 0,
                operator: FilterLogicalOperator.Or,
                uuid: 'group-uuid',
                nestedFilters: [eventFilter, actionFilter],
            }

            const split = splitGroupFilterToLocalFilters(groupFilter, 0)

            expect(split).toHaveLength(2)
            expect(split[0].type).toBe(EntityTypes.EVENTS)
            expect(split[1].type).toBe(EntityTypes.ACTIONS)
        })

        it('preserves properties when splitting', () => {
            const filter = {
                id: '$pageview',
                type: EntityTypes.EVENTS,
                name: '$pageview',
                order: 0,
                uuid: 'uuid-1',
                properties: [
                    {
                        type: 'event',
                        key: 'page_location',
                        value: '/product',
                        operator: 'exact',
                    },
                ],
            }

            const groupFilter = {
                id: null,
                type: EntityTypes.GROUPS,
                name: 'group',
                order: 0,
                operator: FilterLogicalOperator.Or,
                uuid: 'group-uuid',
                nestedFilters: [filter],
            }

            const split = splitGroupFilterToLocalFilters(groupFilter, 0)

            expect(split[0].properties).toEqual(filter.properties)
        })
    })

    describe('single and group filters conversion', () => {
        it('converts single filter to group and back to get same structure', () => {
            const originalFilter = {
                id: '$pageview',
                type: EntityTypes.EVENTS,
                name: '$pageview',
                order: 0,
                uuid: 'uuid-1',
            }

            // Convert to group
            const groupFilter = singleFilterToGroupFilter(originalFilter)

            // Split back
            const split = splitGroupFilterToLocalFilters(groupFilter, 0)

            expect(split).toHaveLength(1)
            expect(split[0]).toEqual(
                expect.objectContaining({
                    id: originalFilter.id,
                    type: originalFilter.type,
                    name: originalFilter.name,
                })
            )
        })

        it('handles multiple filters round-trip', () => {
            const filters = [
                {
                    id: '$pageview',
                    type: EntityTypes.EVENTS,
                    name: '$pageview',
                    order: 0,
                    uuid: 'uuid-1',
                },
                {
                    id: 'signup-action',
                    type: EntityTypes.ACTIONS,
                    name: 'User Signup',
                    order: 1,
                    uuid: 'uuid-2',
                },
            ]

            // Combine first filter to group
            const groupFilter = singleFilterToGroupFilter(filters[0])

            // Split back
            const split = splitGroupFilterToLocalFilters(groupFilter, 0)

            expect(split).toHaveLength(1)
            expect(split[0].id).toBe('$pageview')
        })
    })

    describe('OR vs AND operators', () => {
        it('defaults to OR operator when creating group', () => {
            const filter = {
                id: '$pageview',
                type: EntityTypes.EVENTS,
                name: '$pageview',
                order: 0,
                uuid: 'uuid-1',
            }

            const groupFilter = singleFilterToGroupFilter(filter)

            expect(groupFilter.operator).toBe(FilterLogicalOperator.Or)
        })
    })

    describe('edge cases', () => {
        it('handles empty group filter', () => {
            const groupFilter = {
                id: null,
                type: EntityTypes.GROUPS,
                name: 'empty_group',
                order: 0,
                operator: FilterLogicalOperator.Or,
                uuid: 'group-uuid',
                nestedFilters: [],
            }

            const split = splitGroupFilterToLocalFilters(groupFilter, 0)

            expect(split).toHaveLength(0)
        })

        it('handles single-item group filter', () => {
            const filter = {
                id: '$pageview',
                type: EntityTypes.EVENTS,
                name: '$pageview',
                order: 0,
                uuid: 'uuid-1',
            }

            const groupFilter = {
                id: null,
                type: EntityTypes.GROUPS,
                name: 'single',
                order: 0,
                operator: FilterLogicalOperator.Or,
                uuid: 'group-uuid',
                nestedFilters: [filter],
            }

            const split = splitGroupFilterToLocalFilters(groupFilter, 0)

            expect(split).toHaveLength(1)
            expect(split[0]).toEqual(
                expect.objectContaining({
                    id: '$pageview',
                })
            )
        })

        it('handles large group with many events', () => {
            const filters = Array.from({ length: 10 }, (_, i) => ({
                id: `event-${i}`,
                type: EntityTypes.EVENTS,
                name: `Event ${i}`,
                order: i,
                uuid: `uuid-${i}`,
            }))

            const groupFilter = {
                id: null,
                type: EntityTypes.GROUPS,
                name: 'large_group',
                order: 0,
                operator: FilterLogicalOperator.Or,
                uuid: 'group-uuid',
                nestedFilters: filters,
            }

            const split = splitGroupFilterToLocalFilters(groupFilter, 0)

            expect(split).toHaveLength(10)
            expect(split.map((f) => f.id)).toEqual(Array.from({ length: 10 }, (_, i) => `event-${i}`))
        })
    })

    describe('toLocalFilters with groups', () => {
        it('includes group filters in local filters', () => {
            const filterType = {
                events: [
                    {
                        id: '$pageview',
                        type: EntityTypes.EVENTS,
                        name: '$pageview',
                        order: 0,
                    },
                ],
                groups: [
                    {
                        id: null,
                        type: EntityTypes.GROUPS,
                        name: 'group',
                        order: 1,
                        operator: FilterLogicalOperator.Or,
                        nestedFilters: [
                            {
                                id: '$exception',
                                type: EntityTypes.EVENTS,
                                name: '$exception',
                                order: 0,
                            },
                        ],
                    },
                ],
            }

            const localFilters = toLocalFilters(filterType)

            expect(localFilters).toHaveLength(2)
            expect(localFilters[0]).toEqual(
                expect.objectContaining({
                    id: '$pageview',
                })
            )
            expect(localFilters[1]).toEqual(
                expect.objectContaining({
                    type: EntityTypes.GROUPS,
                })
            )
        })

        it('maintains order across mixed filters and groups', () => {
            const filterType = {
                events: [
                    {
                        id: '$pageview',
                        type: EntityTypes.EVENTS,
                        name: '$pageview',
                        order: 0,
                    },
                    {
                        id: '$pageleave',
                        type: EntityTypes.EVENTS,
                        name: '$pageleave',
                        order: 2,
                    },
                ],
                groups: [
                    {
                        id: null,
                        type: EntityTypes.GROUPS,
                        name: 'group',
                        order: 1,
                        operator: FilterLogicalOperator.Or,
                        nestedFilters: [
                            {
                                id: '$exception',
                                type: EntityTypes.EVENTS,
                                name: '$exception',
                                order: 0,
                            },
                        ],
                    },
                ],
            }

            const localFilters = toLocalFilters(filterType)

            expect(localFilters.map((f) => f.order)).toEqual([0, 1, 2])
        })
    })
})
