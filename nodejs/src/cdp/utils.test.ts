import { DateTime } from 'luxon'

import { Team } from '../types'
import { CdpInternalEvent } from './schema'
import { LogEntry, MinimalLogEntry } from './types'
import {
    convertInternalEventToHogFunctionInvocationGlobals,
    createAddLogFunction,
    fixLogDeduplication,
    getSensitiveValues,
    gzipObject,
    sanitizeLogMessage,
    unGzipObject,
} from './utils'

describe('Utils', () => {
    test.each(['$error_tracking_issue_created', '$error_tracking_issue_reopened', '$error_tracking_issue_spiking'])(
        'flattens exception properties for %s',
        (eventName) => {
            const data: CdpInternalEvent = {
                team_id: 1,
                event: {
                    uuid: '018f0000-0000-7000-8000-000000000000',
                    event: eventName,
                    distinct_id: '018f0000-0000-7000-8000-000000000001',
                    properties: {
                        name: 'Test issue',
                        issue_description: 'Test description',
                        first_seen: '2026-07-20T09:00:00Z',
                        assignee: '{"type":"user","id":42}',
                        fingerprint: 'server-fingerprint',
                        exception_props: {
                            $exception_types: ['TypeError'],
                            assignee: 'untrusted-assignee',
                            fingerprint: 'untrusted-fingerprint',
                        },
                    },
                    timestamp: '2026-07-20T10:00:00Z',
                },
            }

            const globals = convertInternalEventToHogFunctionInvocationGlobals(
                data,
                { id: 1, name: 'Test project' } as Team,
                'https://us.posthog.com'
            )

            expect(globals.event.properties).toEqual({
                name: 'Test issue',
                issue_description: 'Test description',
                first_seen: '2026-07-20T09:00:00Z',
                assignee: '{"type":"user","id":42}',
                fingerprint: 'server-fingerprint',
                $exception_types: ['TypeError'],
            })
        }
    )

    describe('gzip compressions', () => {
        it("should compress and decompress a string using gzip's sync functions", async () => {
            const input = { foo: 'bar', foo2: 'bar' }
            const compressed = await gzipObject(input)
            expect(compressed).toHaveLength(52)
            const decompressed = await unGzipObject(compressed)
            expect(decompressed).toEqual(input)
        })
    })
    describe('fixLogDeduplication', () => {
        const commonProps: Omit<LogEntry, 'timestamp' | 'message'> = {
            team_id: 1,
            log_source: 'hog_function',
            log_source_id: 'hog-1',
            instance_id: 'inv-1',
            level: 'info' as const,
        }
        const startTime = DateTime.fromMillis(1620000000000)
        const example: LogEntry[] = [
            { ...commonProps, timestamp: startTime.plus(2), message: 'Third log message' },
            { ...commonProps, timestamp: startTime, message: 'First log message' },
            { ...commonProps, timestamp: startTime.plus(1), message: 'Second log message' },
            { ...commonProps, timestamp: startTime.plus(2), message: 'Duplicate log message' },
        ]
        it('should add the relevant info to the logs', () => {
            const prepared = fixLogDeduplication(example)
            expect(prepared).toMatchInlineSnapshot(
                `
                [
                  {
                    "instance_id": "inv-1",
                    "level": "info",
                    "log_source": "hog_function",
                    "log_source_id": "hog-1",
                    "message": "First log message",
                    "team_id": 1,
                    "timestamp": "2021-05-03 00:00:00.000",
                  },
                  {
                    "instance_id": "inv-1",
                    "level": "info",
                    "log_source": "hog_function",
                    "log_source_id": "hog-1",
                    "message": "Second log message",
                    "team_id": 1,
                    "timestamp": "2021-05-03 00:00:00.001",
                  },
                  {
                    "instance_id": "inv-1",
                    "level": "info",
                    "log_source": "hog_function",
                    "log_source_id": "hog-1",
                    "message": "Third log message",
                    "team_id": 1,
                    "timestamp": "2021-05-03 00:00:00.002",
                  },
                  {
                    "instance_id": "inv-1",
                    "level": "info",
                    "log_source": "hog_function",
                    "log_source_id": "hog-1",
                    "message": "Duplicate log message",
                    "team_id": 1,
                    "timestamp": "2021-05-03 00:00:00.003",
                  },
                ]
            `
            )
        })
    })
    describe('getSensitiveValues', () => {
        // A webhook's headers input ships as a non-secret dictionary, so nothing in it used to be
        // masked. That is where the API key of the destination most likely to quote it back lives.
        const webhookWithHeaders: any = {
            inputs_schema: [{ key: 'headers', type: 'dictionary', secret: false }],
        }

        it.each([
            ['Authorization', 'Bearer sk_live_abc', ['Bearer sk_live_abc', 'sk_live_abc']],
            ['x-api-key', 'sk_live_abc', ['sk_live_abc']],
        ])('masks the credential under a non-secret %s header', (header, value, expected) => {
            expect(getSensitiveValues(webhookWithHeaders, { headers: { [header]: value } })).toEqual(expected)
        })

        // Redacting these would blank out ordinary headers in every error a destination reports.
        it('leaves headers that carry no credential alone', () => {
            expect(getSensitiveValues(webhookWithHeaders, { headers: { 'Content-Type': 'application/json' } })).toEqual(
                []
            )
        })

        it.each([
            ['integration', { $integration_id: 1, key_info: { private_key: 'nested-private-key' } }],
            ['integration_multi', [{ $integration_id: 1, key_info: { private_key: 'nested-private-key' } }]],
        ])('masks a nested secret in an %s input', (type, value) => {
            const hogFunction: any = { inputs_schema: [{ key: 'connection', type }] }
            expect(getSensitiveValues(hogFunction, { connection: value })).toContain('nested-private-key')
        })

        it('masks a credential-named input that the stored schema leaves non-secret', () => {
            const hogFunction: any = { inputs_schema: [{ key: 'apiKey', type: 'string', secret: false }] }
            expect(getSensitiveValues(hogFunction, { apiKey: 'stale-schema-key' })).toEqual(['stale-schema-key'])
        })
    })

    describe('createAddLogFunction', () => {
        it.each([
            [
                'a derived credential header',
                { headers: { Authorization: 'Basic ZGVyaXZlZC1rZXk6' } },
                'ZGVyaXZlZC1rZXk6',
            ],
            ['a credential under an unlisted header name', { headers: { 'PRIVATE-TOKEN': 'glpat-abc123' } }, 'abc123'],
            ['a response cookie', { headers: { 'set-cookie': 'session=abc123' } }, 'abc123'],
            ['a multi-line secret in a stringified body', { body: JSON.stringify({ key: 'line1\nline2' }) }, 'line2'],
        ])('redacts %s in a logged object', (_name, loggedObject, leakedText) => {
            const logs: MinimalLogEntry[] = []
            createAddLogFunction(logs, ['line1\nline2'])('debug', 'options', loggedObject)
            expect(logs[0].message).toContain('***REDACTED***')
            expect(logs[0].message).not.toContain(leakedText)
        })
    })

    describe('sanitizeLogMessage', () => {
        it('should sanitize the log message', () => {
            const message = sanitizeLogMessage(['test', 'test2'])
            expect(message).toBe('test, test2')
        })
        it.each([
            ['a string argument', ['test', 'test2'], ['test2'], 'test, ***REDACTED***'],
            [
                'a multi-line value in an object',
                [{ key: 'line1\nline2' }],
                ['line1\nline2'],
                '{"key":"***REDACTED***"}',
            ],
            ['a quoted value in an object', [{ key: 'say "hi"' }], ['say "hi"'], '{"key":"***REDACTED***"}'],
            [
                'repeated values that occur inside the marker',
                [{ key: '*' }],
                ['*', '*', '*', '*', '*', '*', '*', '*', 'R'],
                '{"key":"***REDACTED***"}',
            ],
        ])('should redact a sensitive value in %s', (_name, args, sensitiveValues, expected) => {
            expect(sanitizeLogMessage(args, sensitiveValues)).toBe(expected)
        })
        it('should sanitize a range of values types', () => {
            const message = sanitizeLogMessage(['test', 'test2', 1, true, false, null, undefined, { test: 'test' }])
            expect(message).toMatchInlineSnapshot(`"test, test2, 1, true, false, null, , {"test":"test"}"`)
        })
        it('should truncate the log message if it is too long', () => {
            const veryLongMessage = Array(10000).fill('test').join('')
            const message = sanitizeLogMessage([veryLongMessage], [], 10)
            expect(message).toMatchInlineSnapshot(`"testtestte... (truncated)"`)
        })
        it('should not truncate through Unicode surrogate pairs', () => {
            const emoji = '🚀🎉💯🔥'
            const longMessage = emoji + Array(1000).fill('a').join('')
            const message = sanitizeLogMessage([longMessage], [], 10)
            expect(message).not.toMatch(/[\uD800-\uDBFF]$/)
            expect(message).not.toMatch(/[\uDC00-\uDFFF]$/)
            expect(message).toMatch(/\.\.\. \(truncated\)$/)
        })
        it('should handle truncation at exact surrogate pair boundary', () => {
            expect(sanitizeLogMessage(['\ud83c\udf82'], [], 1)).not.toContain('\ud83c')
            expect(sanitizeLogMessage(['🚀🚀🚀🚀🚀'], [], 2)).toMatchInlineSnapshot(`"🚀... (truncated)"`)
            expect(sanitizeLogMessage(['🚀🚀🚀🚀🚀'], [], 3)).toMatchInlineSnapshot(`"🚀... (truncated)"`)
            expect(sanitizeLogMessage(['🚀🚀🚀🚀🚀'], [], 4)).toMatchInlineSnapshot(`"🚀🚀... (truncated)"`)
        })
    })
})
