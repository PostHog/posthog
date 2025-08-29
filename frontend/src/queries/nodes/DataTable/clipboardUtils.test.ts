import Papa from 'papaparse'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import {
    copyTableToCsv,
    copyTableToExcel,
    copyTableToJson,
    flattenObject,
    getCsvTableData,
    getJsonTableData,
} from './clipboardUtils'
import { DataTableRow } from './dataTableLogic'

jest.mock('lib/utils/copyToClipboard')
jest.mock('@posthog/lemon-ui', () => ({
    lemonToast: {
        error: jest.fn(),
    },
}))
jest.mock('papaparse', () => ({
    unparse: jest.fn((data: unknown[][], options: { delimiter?: string } = {}) => {
        const delimiter = options.delimiter || ','
        return data.map((row: unknown[]) => row.join(delimiter)).join('\n')
    }),
}))

const mockCopyToClipboard = copyToClipboard as jest.MockedFunction<typeof copyToClipboard>
const mockLemonToastError = lemonToast.error as jest.MockedFunction<typeof lemonToast.error>
const mockPapaUnparse = Papa.unparse as jest.MockedFunction<typeof Papa.unparse>

type DataTableSourceKind = DataTableNode['source']['kind']

const createMockQuery = (
    sourceKind: DataTableSourceKind,
    additionalProps: Record<string, unknown> = {}
): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    source: { kind: sourceKind, ...additionalProps } as DataTableNode['source'],
})

describe('clipboardUtils', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('flattenObject', () => {
        it('returns primitive values with default key when prefix is provided', () => {
            expect(flattenObject('test', 'someKey')).toEqual({ someKey: 'test' })
            expect(flattenObject(123, 'someKey')).toEqual({ someKey: 123 })
            expect(flattenObject(true, 'someKey')).toEqual({ someKey: true })
            expect(flattenObject(null, 'someKey')).toEqual({ someKey: null })
            expect(flattenObject(undefined, 'someKey')).toEqual({ someKey: undefined })
        })

        it('returns raw primitive values when prefix is empty string', () => {
            expect(flattenObject('test', '')).toBe('test')
            expect(flattenObject(123, '')).toBe(123)
            expect(flattenObject(true, '')).toBe(true)
            expect(flattenObject(null, '')).toBe(null)
            expect(flattenObject(undefined, '')).toBe(undefined)
        })

        it('returns arrays with default key when prefix is provided', () => {
            const arr = [1, 2, 3]
            expect(flattenObject(arr, 'someKey')).toEqual({ someKey: arr })
        })

        it('returns raw arrays when prefix is empty string', () => {
            const arr = [1, 2, 3]
            expect(flattenObject(arr, '')).toBe(arr)
        })

        it('uses fallback "value" key when prefix is null/undefined', () => {
            expect(flattenObject('test', null as any)).toEqual({ value: 'test' })
            expect(flattenObject('test', undefined)).toEqual({ value: 'test' })
        })

        it('flattens nested objects', () => {
            const nested = {
                level1: {
                    level2: { value: 'deep' },
                    simple: 'test',
                },
                direct: 'value',
            }
            expect(flattenObject(nested)).toEqual({
                'level1.level2.value': 'deep',
                'level1.simple': 'test',
                direct: 'value',
            })
        })

        it('uses custom prefix and separator', () => {
            const obj = { a: { b: 'value' } }
            expect(flattenObject(obj, 'prefix', '_')).toEqual({
                prefix_a_b: 'value',
            })
        })

        it('handles mixed data types', () => {
            const complex = {
                string: 'test',
                number: 42,
                boolean: true,
                nullValue: null,
                arrayValue: [1, 2, 3],
                nested: { deep: 'value' },
            }
            expect(flattenObject(complex, 'root')).toEqual({
                'root.string': 'test',
                'root.number': 42,
                'root.boolean': true,
                'root.nullValue': null,
                'root.arrayValue': [1, 2, 3],
                'root.nested.deep': 'value',
            })
        })
    })

    describe('getCsvTableData', () => {
        it('handles EventsQuery with person column', () => {
            const query = createMockQuery(NodeKind.EventsQuery, { select: ['event', 'person'] })
            const columns = ['event', 'person']
            const rows: DataTableRow[] = [
                {
                    result: [
                        'pageview',
                        {
                            distinct_id: 'user_123',
                            properties: { email: 'john@example.com' },
                        },
                    ],
                },
            ]

            const result = getCsvTableData(rows, columns, query)

            expect(result[0]).toContain('event')
            expect(result[0]).toContain('person')
            expect(result[1][0]).toBe('pageview')
            expect(result[1][1]).toBe('john@example.com') // asDisplay returns email (person display property)
        })

        it('handles PersonsNode with nested properties', () => {
            const query = createMockQuery(NodeKind.PersonsNode)
            const columns = ['email', 'properties']
            const rows: DataTableRow[] = [
                {
                    result: {
                        email: 'test@example.com',
                        properties: { age: 25, location: { city: 'NYC' } },
                        name: 'Test User',
                    },
                },
            ]

            const result = getCsvTableData(rows, columns, query)

            expect(result[0]).toContain('email')
            expect(result[0]).toContain('properties.age')
            expect(result[0]).toContain('properties.location.city')
            expect(result[1]).toContain('test@example.com')
            expect(result[1]).toContain(25)
            expect(result[1]).toContain('NYC')
        })

        it('handles HogQLQuery source', () => {
            const query = createMockQuery(NodeKind.HogQLQuery, { query: 'SELECT * FROM events' })
            const columns = ['event', 'properties']
            const rows: DataTableRow[] = [{ result: ['click', { button_id: 'submit', metadata: { source: 'form' } }] }]

            const result = getCsvTableData(rows, columns, query)

            expect(result[0]).toContain('event')
            expect(result[0]).toContain('properties.button_id')
            expect(result[0]).toContain('properties.metadata.source')
            expect(result[1]).toContain('click')
            expect(result[1]).toContain('submit')
            expect(result[1]).toContain('form')
        })

        it('returns empty array for unsupported query types', () => {
            // Create a query with an unsupported source by bypassing type safety
            const query: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: { kind: 'UnsupportedQuery' as any },
            }
            const result = getCsvTableData([], ['event'], query)

            expect(result).toEqual([])
        })
    })

    describe('getJsonTableData', () => {
        it('handles EventsQuery with column extraction', () => {
            const query = createMockQuery(NodeKind.EventsQuery, { select: ['event', 'timestamp -- Timestamp'] })
            const columns = ['event', 'timestamp -- Timestamp']
            const rows: DataTableRow[] = [{ result: ['pageview', '2023-01-01T00:00:00Z'] }]

            const result = getJsonTableData(rows, columns, query)

            expect(result).toHaveLength(1)
            expect(result[0].event).toBe('pageview')
            expect(result[0].Timestamp).toBe('2023-01-01T00:00:00Z')
        })

        it('handles PersonsNode source', () => {
            const query = createMockQuery(NodeKind.PersonsNode)
            const columns = ['email', 'created_at']
            const rows: DataTableRow[] = [
                { result: { email: 'test@example.com', created_at: '2023-01-01', name: 'Test User' } },
            ]

            const result = getJsonTableData(rows, columns, query)

            expect(result).toHaveLength(1)
            expect(result[0].email).toBe('test@example.com')
            expect(result[0].created_at).toBe('2023-01-01')
        })

        it('handles HogQLQuery source', () => {
            const query = createMockQuery(NodeKind.HogQLQuery, { query: 'SELECT * FROM events' })
            const columns = ['event', 'count']
            const rows: DataTableRow[] = [{ result: ['pageview', 42] }]

            const result = getJsonTableData(rows, columns, query)

            expect(result).toHaveLength(1)
            expect(result[0].event).toBe('pageview')
            expect(result[0].count).toBe(42)
        })

        it('filters disallowed columns', () => {
            const query = createMockQuery(NodeKind.EventsQuery, { select: ['event', 'person.$delete'] })
            const columns = ['event', 'person.$delete']
            const rows: DataTableRow[] = [{ result: ['pageview', 'delete_value'] }]

            const result = getJsonTableData(rows, columns, query)

            expect(result).toHaveLength(1)
            expect(result[0].event).toBe('pageview')
            expect(result[0]['person.$delete']).toBeUndefined()
        })

        it('returns empty array for unsupported query types', () => {
            // Create a query with an unsupported source by bypassing type safety
            const query: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: { kind: 'UnsupportedQuery' as any },
            }
            const result = getJsonTableData([], ['event'], query)

            expect(result).toEqual([])
        })
    })

    describe('copyTableToCsv', () => {
        it('copies CSV data to clipboard', () => {
            const query = createMockQuery(NodeKind.HogQLQuery, { query: 'SELECT * FROM events' })
            const columns = ['event']
            const rows: DataTableRow[] = [{ result: ['pageview'] }]

            copyTableToCsv(rows, columns, query)

            expect(mockCopyToClipboard).toHaveBeenCalledWith('event\npageview', 'table')
        })

        it('shows error on copy failure', () => {
            mockCopyToClipboard.mockImplementation(() => {
                throw new Error('Copy failed')
            })
            const query = createMockQuery(NodeKind.HogQLQuery, { query: 'SELECT * FROM events' })

            copyTableToCsv([{ result: ['pageview'] }], ['event'], query)

            expect(mockLemonToastError).toHaveBeenCalledWith('Copy failed!')
        })
    })

    describe('copyTableToJson', () => {
        it('copies JSON data to clipboard', () => {
            const query = createMockQuery(NodeKind.HogQLQuery, { query: 'SELECT * FROM events' })
            const columns = ['event']
            const rows: DataTableRow[] = [{ result: ['pageview'] }]

            copyTableToJson(rows, columns, query)

            const expectedJson = JSON.stringify([{ event: 'pageview' }], null, 4)
            expect(mockCopyToClipboard).toHaveBeenCalledWith(expectedJson, 'table')
        })

        it('shows error on copy failure', () => {
            mockCopyToClipboard.mockImplementation(() => {
                throw new Error('Copy failed')
            })
            const query = createMockQuery(NodeKind.HogQLQuery, { query: 'SELECT * FROM events' })

            copyTableToJson([{ result: ['pageview'] }], ['event'], query)

            expect(mockLemonToastError).toHaveBeenCalledWith('Copy failed!')
        })
    })

    describe('copyTableToExcel', () => {
        it('copies TSV data with tab delimiter', () => {
            const query = createMockQuery(NodeKind.HogQLQuery, { query: 'SELECT * FROM events' })
            const columns = ['event', 'timestamp', 'user_id']
            const rows: DataTableRow[] = [
                { result: ['pageview', '2023-01-01T00:00:00Z', 'user123'] },
                { result: ['click', '2023-01-01T00:01:00Z', 'user456'] },
            ]

            copyTableToExcel(rows, columns, query)

            const expectedData = [
                ['event', 'timestamp', 'user_id'],
                ['pageview', '2023-01-01T00:00:00Z', 'user123'],
                ['click', '2023-01-01T00:01:00Z', 'user456'],
            ]
            expect(mockPapaUnparse).toHaveBeenCalledWith(expectedData, { delimiter: '\t' })

            const expectedOutput =
                'event\ttimestamp\tuser_id\npageview\t2023-01-01T00:00:00Z\tuser123\nclick\t2023-01-01T00:01:00Z\tuser456'
            expect(mockCopyToClipboard).toHaveBeenCalledWith(expectedOutput, 'table')
        })

        it('shows error on copy failure', () => {
            mockCopyToClipboard.mockImplementation(() => {
                throw new Error('Copy failed')
            })
            const query = createMockQuery(NodeKind.HogQLQuery, { query: 'SELECT * FROM events' })

            copyTableToExcel([{ result: ['pageview'] }], ['event'], query)

            expect(mockLemonToastError).toHaveBeenCalledWith('Copy failed!')
        })

        it('handles Papa.unparse failure', () => {
            mockPapaUnparse.mockImplementation(() => {
                throw new Error('Papa parse failed')
            })
            const query = createMockQuery(NodeKind.HogQLQuery, { query: 'SELECT * FROM events' })

            copyTableToExcel([{ result: ['pageview'] }], ['event'], query)

            expect(mockLemonToastError).toHaveBeenCalledWith('Copy failed!')
        })
    })

    describe('edge cases and failures', () => {
        it('handles data with circular references in JSON', () => {
            // Create circular reference
            const circularObj: any = { name: 'test' }
            circularObj.self = circularObj

            const query = createMockQuery(NodeKind.PersonsNode)
            const rows: DataTableRow[] = [{ result: circularObj }]

            // Mock JSON.stringify to throw on circular reference
            const originalStringify = JSON.stringify
            jest.spyOn(JSON, 'stringify').mockImplementation(() => {
                throw new TypeError('Converting circular structure to JSON')
            })

            copyTableToJson(rows, ['name'], query)

            expect(mockLemonToastError).toHaveBeenCalledWith('Copy failed!')

            // Restore original
            JSON.stringify = originalStringify
        })
    })
})
