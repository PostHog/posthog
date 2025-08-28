import { MarketingAnalyticsTableQuery, NodeKind } from '~/queries/schema/schema-general'

import { getOrderBy, getSortedColumnsByArray, orderArrayByPreference } from './utils'

describe('marketing analytics utils', () => {
    describe('getOrderBy', () => {
        it('should filter order by columns that exist in the columns list', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign', 'source'],
                orderBy: [
                    ['campaign', 'ASC'],
                    ['source', 'DESC'],
                    ['non_existent_column', 'ASC'],
                ],
            }
            const columns = ['campaign', 'source', 'other_column']

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(2)
            expect(result.some((order) => order[0] === 'campaign' && order[1] === 'ASC')).toBe(true)
            expect(result.some((order) => order[0] === 'source' && order[1] === 'DESC')).toBe(true)
            expect(result.some((order) => order[0] === 'non_existent_column')).toBe(false)
        })

        it('should return empty array when query is undefined', () => {
            const columns = ['campaign', 'source']

            const result = getOrderBy(undefined, columns)

            expect(result.length).toBe(0)
        })

        it('should return empty array when query has no orderBy', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign', 'source'],
            }
            const columns = ['campaign', 'source']

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(0)
        })

        it('should return empty array when no order by columns exist in columns list', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign', 'source'],
                orderBy: [
                    ['non_existent_column', 'ASC'],
                    ['another_non_existent', 'DESC'],
                ],
            }
            const columns = ['campaign', 'source']

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(0)
        })

        it('should handle empty columns list', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign'],
                orderBy: [['campaign', 'ASC']],
            }
            const columns: string[] = []

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(0)
        })

        it('should preserve order of valid order by columns', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign', 'source', 'medium'],
                orderBy: [
                    ['campaign', 'ASC'],
                    ['non_existent', 'DESC'],
                    ['source', 'DESC'],
                    ['medium', 'ASC'],
                ],
            }
            const columns = ['campaign', 'source', 'medium']

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(3)
            expect(result[0][0]).toBe('campaign')
            expect(result[1][0]).toBe('source')
            expect(result[2][0]).toBe('medium')
        })
    })

    describe('orderArrayByPreference', () => {
        it('should order array by preference with items in preference first', () => {
            const array = ['a', 'b', 'c']
            const preference = ['c', 'b']

            const result = orderArrayByPreference(array, preference)

            expect(result).toEqual(['b', 'c', 'a'])
        })

        it('should handle empty preference array', () => {
            const array = ['a', 'b', 'c']
            const preference: string[] = []

            const result = orderArrayByPreference(array, preference)

            expect(result).toEqual(['a', 'b', 'c'])
        })

        it('should handle empty array', () => {
            const array: string[] = []
            const preference = ['c', 'b']

            const result = orderArrayByPreference(array, preference)

            expect(result).toEqual([])
        })

        it('should handle preference with items not in array', () => {
            const array = ['a', 'b', 'c']
            const preference = ['d', 'e', 'b']

            const result = orderArrayByPreference(array, preference)

            expect(result).toEqual(['b', 'a', 'c'])
        })

        it('should handle duplicate items in preference', () => {
            const array = ['a', 'b', 'c']
            const preference = ['b', 'b', 'c']

            const result = orderArrayByPreference(array, preference)

            expect(result).toEqual(['b', 'c', 'a'])
        })

        it('should preserve order within preference groups', () => {
            const array = ['a', 'b', 'c', 'd']
            const preference = ['c', 'a']

            const result = orderArrayByPreference(array, preference)

            expect(result).toEqual(['a', 'c', 'b', 'd'])
        })
    })

    describe('getSortedColumnsByArray', () => {
        it('should sort columns by sortedArray order', () => {
            const array = ['a', 'b', 'c']
            const sortedArray = ['c', 'b']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['c', 'b', 'a'])
        })

        it('should handle empty sortedArray', () => {
            const array = ['a', 'b', 'c']
            const sortedArray: string[] = []

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['a', 'b', 'c'])
        })

        it('should handle empty array', () => {
            const array: string[] = []
            const sortedArray = ['c', 'b']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual([])
        })

        it('should handle sortedArray with items not in array', () => {
            const array = ['a', 'b', 'c']
            const sortedArray = ['d', 'e', 'b', 'f']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['b', 'a', 'c'])
        })

        it('should handle duplicate items in sortedArray', () => {
            const array = ['a', 'b', 'c']
            const sortedArray = ['b', 'b', 'c', 'b']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['b', 'c', 'a'])
        })

        it('should preserve order of items not in sortedArray', () => {
            const array = ['a', 'b', 'c', 'd', 'e']
            const sortedArray = ['c', 'a']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['c', 'a', 'b', 'd', 'e'])
        })

        it('should handle case where all items are in sortedArray', () => {
            const array = ['a', 'b', 'c', 'a']
            const sortedArray = ['c', 'a', 'b', 'b']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['c', 'a', 'a', 'b'])
        })

        it('should handle case where no items are in sortedArray', () => {
            const array = ['a', 'b', 'c']
            const sortedArray = ['d', 'e', 'f']

            const result = getSortedColumnsByArray(array, sortedArray)

            expect(result).toEqual(['a', 'b', 'c'])
        })
    })
})
