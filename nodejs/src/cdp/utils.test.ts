import { DateTime } from 'luxon'

import { LogEntry } from './types'
import { fixLogDeduplication, gzipObject, sanitizeLogMessage, unGzipObject } from './utils'

describe('Utils', () => {
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
    describe('sanitizeLogMessage', () => {
        it('should sanitize the log message', () => {
            const message = sanitizeLogMessage(['test', 'test2'])
            expect(message).toBe('test, test2')
        })
        it('should sanitize the log message with a sensitive value', () => {
            const message = sanitizeLogMessage(['test', 'test2'], ['test2'])
            expect(message).toBe('test, ***REDACTED***')
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
