import { Message } from 'node-rdkafka'

import { parseEventHeaders } from '../../kafka/consumer'
import { EventHeaders } from '../../types'
import { ok } from '../pipelines/results'
import { createParseHeadersStep } from './parse-headers'

// Mock dependencies
jest.mock('../../../src/kafka/consumer', () => ({
    parseEventHeaders: jest.fn(),
}))

describe('createParseHeadersStep', () => {
    const mockParseEventHeaders = parseEventHeaders as jest.MockedFunction<typeof parseEventHeaders>
    let step: ReturnType<typeof createParseHeadersStep>

    beforeEach(() => {
        jest.clearAllMocks()
        step = createParseHeadersStep()
    })

    it('should parse headers and return success with headers', async () => {
        const input = {
            message: {
                headers: [{ token: Buffer.from('test-token') }, { distinct_id: Buffer.from('test-user') }],
            } as Pick<Message, 'headers'>,
        }

        const expectedHeaders: EventHeaders = {
            token: 'test-token',
            distinct_id: 'test-user',
        }

        mockParseEventHeaders.mockReturnValue(expectedHeaders)

        const result = await step(input)

        expect(result).toEqual(ok({ ...input, headers: expectedHeaders }))
        expect(mockParseEventHeaders).toHaveBeenCalledWith(input.message.headers)
    })

    it('should preserve additional input properties', async () => {
        const expectedHeaders: EventHeaders = {
            token: 'test-token',
        }

        mockParseEventHeaders.mockReturnValue(expectedHeaders)

        const input = {
            message: {
                headers: [{ token: Buffer.from('test-token') }],
            } as Pick<Message, 'headers'>,
            customField: 'custom-value',
            anotherField: 42,
        }
        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                headers: expectedHeaders,
            })
        )
        expect(mockParseEventHeaders).toHaveBeenCalledWith(input.message.headers)
    })

    it('should handle empty headers', async () => {
        const expectedHeaders: EventHeaders = {}

        mockParseEventHeaders.mockReturnValue(expectedHeaders)

        const input = {
            message: {
                headers: [],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(ok({ ...input, headers: expectedHeaders }))
        expect(mockParseEventHeaders).toHaveBeenCalledWith(input.message.headers)
    })

    it('should handle undefined headers', async () => {
        const expectedHeaders: EventHeaders = {}

        mockParseEventHeaders.mockReturnValue(expectedHeaders)

        const input = {
            message: {
                headers: undefined,
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(ok({ ...input, headers: expectedHeaders }))
        expect(mockParseEventHeaders).toHaveBeenCalledWith(input.message.headers)
    })

    it('should handle headers with duplicate keys (last value wins)', async () => {
        const expectedHeaders: EventHeaders = {
            token: 'second-token',
            distinct_id: 'second-user',
        }

        mockParseEventHeaders.mockReturnValue(expectedHeaders)

        const input = {
            message: {
                headers: [
                    { token: Buffer.from('first-token') },
                    { distinct_id: Buffer.from('first-user') },
                    { token: Buffer.from('second-token') }, // This should overwrite the first token
                    { distinct_id: Buffer.from('second-user') }, // This should overwrite the first distinct_id
                ],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(ok({ ...input, headers: expectedHeaders }))
        expect(mockParseEventHeaders).toHaveBeenCalledWith(input.message.headers)
    })

    it('should handle complex headers with multiple supported fields', async () => {
        const expectedHeaders: EventHeaders = {
            token: 'complex-token',
            distinct_id: 'complex-user',
            timestamp: '2023-01-01T00:00:00Z',
        }

        mockParseEventHeaders.mockReturnValue(expectedHeaders)

        const input = {
            message: {
                headers: [
                    { token: Buffer.from('complex-token') },
                    { distinct_id: Buffer.from('complex-user') },
                    { timestamp: Buffer.from('2023-01-01T00:00:00Z') },
                ],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(ok({ ...input, headers: expectedHeaders }))
        expect(mockParseEventHeaders).toHaveBeenCalledWith(input.message.headers)
    })

    it('should handle string values in headers', async () => {
        const expectedHeaders: EventHeaders = {
            token: 'string-token',
            distinct_id: 'string-user',
            timestamp: '2023-01-01T00:00:00Z',
        }

        mockParseEventHeaders.mockReturnValue(expectedHeaders)

        const input = {
            message: {
                headers: [
                    { token: 'string-token' },
                    { distinct_id: 'string-user' },
                    { timestamp: '2023-01-01T00:00:00Z' },
                ],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(ok({ ...input, headers: expectedHeaders }))
        expect(mockParseEventHeaders).toHaveBeenCalledWith(input.message.headers)
    })

    it('should handle mixed Buffer and string values in headers', async () => {
        const expectedHeaders: EventHeaders = {
            token: 'buffer-token',
            distinct_id: 'string-user',
            timestamp: '2023-01-01T00:00:00Z',
        }

        mockParseEventHeaders.mockReturnValue(expectedHeaders)

        const input = {
            message: {
                headers: [
                    { token: Buffer.from('buffer-token') },
                    { distinct_id: 'string-user' },
                    { timestamp: Buffer.from('2023-01-01T00:00:00Z') },
                ],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(ok({ ...input, headers: expectedHeaders }))
        expect(mockParseEventHeaders).toHaveBeenCalledWith(input.message.headers)
    })

    it('should ignore unsupported headers and only parse supported ones', async () => {
        const expectedHeaders: EventHeaders = {
            token: 'test-token',
            distinct_id: 'test-user',
        }

        mockParseEventHeaders.mockReturnValue(expectedHeaders)

        const input = {
            message: {
                headers: [
                    { token: Buffer.from('test-token') },
                    { distinct_id: Buffer.from('test-user') },
                    { unsupported_header: Buffer.from('should-be-ignored') },
                    { ip: Buffer.from('192.168.1.1') },
                    { site_url: Buffer.from('https://example.com') },
                    { custom_field: Buffer.from('custom-value') },
                ],
            } as Pick<Message, 'headers'>,
        }
        const result = await step(input)

        expect(result).toEqual(ok({ ...input, headers: expectedHeaders }))
        expect(mockParseEventHeaders).toHaveBeenCalledWith(input.message.headers)
    })
})
