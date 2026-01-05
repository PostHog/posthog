import { PluginEvent } from '@posthog/plugin-scaffold'

import { processAiErrorNormalization } from './index'
import { normalizeError } from './normalize-error'

describe('normalizeError', () => {
    describe('UUID and request ID normalization', () => {
        it.each([
            ['Request req_abc123def456 failed', 'Request <ID> failed'],
            ['Request req_xyz789ghi012 failed', 'Request <ID> failed'],
            ['Error 550e8400-e29b-41d4-a716-446655440000 occurred', 'Error <ID> occurred'],
            ['Error 123e4567-e89b-12d3-a456-426614174000 occurred', 'Error <ID> occurred'],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('timestamp normalization', () => {
        it.each([
            ['Timeout at 2025-11-08T14:25:51.767Z', 'Timeout at <TIMESTAMP>'],
            ['Timeout at 2025-11-09T10:30:22.123Z', 'Timeout at <TIMESTAMP>'],
            ['Error at 2024-01-15T00:00:00.000', 'Error at <TIMESTAMP>'],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('GCP path normalization', () => {
        it.each([
            [
                'Model projects/123/locations/us-west2/publishers/google/models/gemini-pro not found',
                'Model projects/<PATH> not found',
            ],
            [
                'Model projects/456/locations/europe-west1/publishers/google/models/claude-2 not found',
                'Model projects/<PATH> not found',
            ],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('response ID normalization', () => {
        it.each([
            ['API error: "responseId":"h2sPacmZI4OWvPEPvIS16Ac"', 'API error: "responseId":"<RESPONSE_ID>"'],
            ['API error: "responseId":"abcXYZ123def456GHI789"', 'API error: "responseId":"<RESPONSE_ID>"'],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('JSON id field normalization', () => {
        it.each([
            ['{"id": "oJf6eVw-z1gNr-99c2d11d156dff07", "error": "test"}', '{"id": "<ID>", "error": "test"}'],
            ['{"id": "abc123xyz789", "error": "test"}', '{"id": "<ID>", "error": "test"}'],
            ['{"id":"different-id-format", "error": "test"}', '{"id": "<ID>", "error": "test"}'],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('tool call ID normalization', () => {
        it.each([
            ["tool_call_id='toolu_01LCbNr67BxhgUH6gndPCELW' failed", "tool_call_id='<TOOL_CALL_ID>' failed"],
            ["tool_call_id='toolu_99XYZabcDEF123ghiJKL456' failed", "tool_call_id='<TOOL_CALL_ID>' failed"],
            [
                'tool_use ids were found without tool_result blocks: toolu_01Bj5f7R5g9vhe7MkEyFT6Ty',
                'tool_use ids were found without tool_result blocks: <TOOL_ID>',
            ],
            [
                'tool_use ids were found without tool_result blocks: toolu_99XYZabcDEF123ghiJKL456',
                'tool_use ids were found without tool_result blocks: <TOOL_ID>',
            ],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('function call ID normalization', () => {
        it.each([
            [
                'No tool output found for function call call_edLiisyOJybNZLouC6MCNxyC.',
                'No tool output found for function call call_<CALL_ID>.',
            ],
            [
                'No tool output found for function call call_abc123def456ghi789jkl012.',
                'No tool output found for function call call_<CALL_ID>.',
            ],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('user ID normalization', () => {
        it.each([
            [
                "Error 'user_id': 'user_32yQoBNWxpvzxVJG0S0zxnnVSCJ' occurred",
                "Error 'user_id': 'user_<USER_ID>' occurred",
            ],
            ["Error 'user_id': 'user_abc123xyz789def456' occurred", "Error 'user_id': 'user_<USER_ID>' occurred"],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('object ID (hex address) normalization', () => {
        it.each([
            ['CancelledError: <object object at 0xfffced405130>', 'CancelledError: <object object at <OBJECT_ID>>'],
            ['CancelledError: <object object at 0xaaabec123456>', 'CancelledError: <object object at <OBJECT_ID>>'],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('generic ID normalization', () => {
        it.each([
            ["Error with id='e8631f8c4650120cd5848570185bbcd7' occurred", "Error with id='<ID>' occurred"],
            ["Error with id='a1b2c3d4e5f6a0b1c2d3e4f5abcdef01' occurred", "Error with id='<ID>' occurred"],
            ["Error with id='s1' occurred", "Error with id='<ID>' occurred"],
            ["Error with id='user_abc123' occurred", "Error with id='<ID>' occurred"],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('token count normalization', () => {
        it.each([
            ['Limit exceeded: "tokenCount":7125', 'Limit exceeded: "tokenCount":<TOKEN_COUNT>'],
            ['Limit exceeded: "tokenCount":15000', 'Limit exceeded: "tokenCount":<TOKEN_COUNT>'],
            ['Limit exceeded: "tokenCount": 7125', 'Limit exceeded: "tokenCount":<TOKEN_COUNT>'],
            ['Limit exceeded: "tokenCount":  15000', 'Limit exceeded: "tokenCount":<TOKEN_COUNT>'],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('large numeric ID normalization', () => {
        it.each([
            ['Error in project 1234567890', 'Error in project <ID>'],
            ['Error in project 9876543210', 'Error in project <ID>'],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('general number normalization', () => {
        it.each([
            ['Expected 2 arguments but got 5', 'Expected <N> arguments but got <N>'],
            ['Expected 10 arguments but got 15', 'Expected <N> arguments but got <N>'],
            ['Connection refused on port 8080', 'Connection refused on port <N>'],
            ['Connection refused on port 3000', 'Connection refused on port <N>'],
            ['Request failed with status 429', 'Request failed with status <N>'],
            ['Request failed with status 500', 'Request failed with status <N>'],
        ])('normalizes "%s" to "%s"', (input, expected) => {
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('complex errors with multiple normalizations', () => {
        it('normalizes errors with timestamps, IDs, token counts, and status codes', () => {
            const input =
                'Error at 2025-11-08T14:25:51.767Z in project 1234567890: "responseId":"abc123", "tokenCount":5000, tool_call_id=\'toolu_XYZ\' (status 429)'
            const expected =
                'Error at <TIMESTAMP> in project <ID>: "responseId":"<RESPONSE_ID>", "tokenCount":<TOKEN_COUNT>, tool_call_id=\'<TOOL_CALL_ID>\' (status <N>)'
            expect(normalizeError(input)).toBe(expected)
        })

        it('normalizes combined patterns', () => {
            const input =
                '{"id": "oJf6eVw-z1gNr-99c2d11d156dff07"} function call call_edLiisyOJybNZLouC6MCNxyC \'user_id\': \'user_32yQoBNWxpvzxVJG0S0zxnnVSCJ\' at <object object at 0xfffced405130>'
            const expected =
                '{"id": "<ID>"} function call call_<CALL_ID> \'user_id\': \'user_<USER_ID>\' at <object object at <OBJECT_ID>>'
            expect(normalizeError(input)).toBe(expected)
        })

        it('normalizes overloaded error format', () => {
            const input = 'Error: {"type":"error","error":{"type":"overloaded_error"},"request_id":"req_abc123"}'
            const expected = 'Error: {"type":"error","error":{"type":"overloaded_error"},"request_id":"<ID>"}'
            expect(normalizeError(input)).toBe(expected)
        })
    })

    describe('whitespace normalization', () => {
        it('collapses multiple spaces', () => {
            expect(normalizeError('Error   with   spaces')).toBe('Error with spaces')
        })

        it('trims leading and trailing whitespace', () => {
            expect(normalizeError('  Error message  ')).toBe('Error message')
        })

        it('normalizes tabs and newlines', () => {
            expect(normalizeError('Error\twith\ttabs')).toBe('Error with tabs')
            expect(normalizeError('Error\nwith\nnewlines')).toBe('Error with newlines')
        })
    })

    describe('preserves error identity', () => {
        it('does not match common words like user_input', () => {
            expect(normalizeError('Error in user_input validation')).toBe('Error in user_input validation')
        })

        it('does not match call_function', () => {
            expect(normalizeError('Failed to call_function properly')).toBe('Failed to call_function properly')
        })

        it('does not match user_error', () => {
            expect(normalizeError('Problem with user_error handling')).toBe('Problem with user_error handling')
        })
    })

    describe('edge cases', () => {
        it('handles empty string', () => {
            expect(normalizeError('')).toBe('')
        })

        it('handles null-like input', () => {
            expect(normalizeError(null as unknown as string)).toBe('')
            expect(normalizeError(undefined as unknown as string)).toBe('')
        })

        it('handles string with only whitespace', () => {
            expect(normalizeError('   ')).toBe('')
        })
    })

    describe('truncation', () => {
        it('truncates very long error messages', () => {
            const longError = 'Error: ' + 'x'.repeat(2000)
            const result = normalizeError(longError)
            expect(result.length).toBeLessThanOrEqual(1003) // 1000 + '...'
            expect(result).toMatch(/\.\.\.$/)
        })

        it('does not truncate short error messages', () => {
            const shortError = 'Error: something went wrong'
            const result = normalizeError(shortError)
            expect(result).toBe('Error: something went wrong')
            expect(result).not.toMatch(/\.\.\.$/)
        })
    })
})

describe('processAiErrorNormalization', () => {
    const createEvent = (properties: Record<string, unknown>): PluginEvent => ({
        distinct_id: 'user_123',
        ip: null,
        site_url: '',
        team_id: 1,
        now: new Date().toISOString(),
        event: '$ai_generation',
        uuid: '123e4567-e89b-12d3-a456-426614174000',
        properties,
    })

    it('adds $ai_error_normalized for error events', () => {
        const event = createEvent({
            $ai_is_error: true,
            $ai_error: 'Request req_abc123 failed with status 500',
        })

        const result = processAiErrorNormalization(event)

        expect(result.properties!['$ai_error_normalized']).toBe('Request <ID> failed with status <N>')
    })

    it('handles $ai_is_error as string "true"', () => {
        const event = createEvent({
            $ai_is_error: 'true',
            $ai_error: 'Error 12345',
        })

        const result = processAiErrorNormalization(event)

        expect(result.properties!['$ai_error_normalized']).toBe('Error <N>')
    })

    it('does not add $ai_error_normalized for non-error events', () => {
        const event = createEvent({
            $ai_is_error: false,
            $ai_error: 'Some message',
        })

        const result = processAiErrorNormalization(event)

        expect(result.properties!['$ai_error_normalized']).toBeUndefined()
    })

    it('does not add $ai_error_normalized when $ai_is_error is missing', () => {
        const event = createEvent({
            $ai_error: 'Some message',
        })

        const result = processAiErrorNormalization(event)

        expect(result.properties!['$ai_error_normalized']).toBeUndefined()
    })

    it('does not add $ai_error_normalized when $ai_error is missing', () => {
        const event = createEvent({
            $ai_is_error: true,
        })

        const result = processAiErrorNormalization(event)

        expect(result.properties!['$ai_error_normalized']).toBeUndefined()
    })

    it('handles events without properties', () => {
        const event: PluginEvent = {
            distinct_id: 'user_123',
            ip: null,
            site_url: '',
            team_id: 1,
            now: new Date().toISOString(),
            event: '$ai_generation',
            uuid: '123e4567-e89b-12d3-a456-426614174000',
        }

        const result = processAiErrorNormalization(event)

        expect(result).toBe(event)
    })

    it('converts non-string $ai_error to string', () => {
        const event = createEvent({
            $ai_is_error: true,
            $ai_error: 12345,
        })

        const result = processAiErrorNormalization(event)

        expect(result.properties!['$ai_error_normalized']).toBe('<N>')
    })

    it('JSON stringifies object $ai_error', () => {
        const event = createEvent({
            $ai_is_error: true,
            $ai_error: { status: 400, message: 'Bad request', requestId: 'req_abc123' },
        })

        const result = processAiErrorNormalization(event)

        expect(result.properties!['$ai_error_normalized']).toBe(
            '{"status":<N>,"message":"Bad request","requestId":"<ID>"}'
        )
    })

    it('JSON stringifies array $ai_error', () => {
        const event = createEvent({
            $ai_is_error: true,
            $ai_error: ['Error 1', 'Error 2'],
        })

        const result = processAiErrorNormalization(event)

        expect(result.properties!['$ai_error_normalized']).toBe('["Error <N>","Error <N>"]')
    })

    it('respects user-provided $ai_error_normalized', () => {
        const event = createEvent({
            $ai_is_error: true,
            $ai_error: 'Error with req_abc123',
            $ai_error_normalized: 'Custom normalized error',
        })

        const result = processAiErrorNormalization(event)

        expect(result.properties!['$ai_error_normalized']).toBe('Custom normalized error')
    })
})
