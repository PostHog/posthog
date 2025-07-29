import { DateTime } from 'luxon'

import { LogEntry } from './types'
import { fixLogDeduplication, gzipObject, unGzipObject } from './utils'

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
            {
                ...commonProps,
                timestamp: startTime.plus(2),
                message: 'Third log message',
            },
            {
                ...commonProps,
                timestamp: startTime,
                message: 'First log message',
            },
            {
                ...commonProps,
                timestamp: startTime.plus(1),
                message: 'Second log message',
            },
            {
                ...commonProps,
                timestamp: startTime.plus(2),
                message: 'Duplicate log message',
            },
        ]

        it('should add the relevant info to the logs', () => {
            const prepared = fixLogDeduplication(example)

            expect(prepared).toMatchInlineSnapshot(`
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
            `)
        })
    })
})
