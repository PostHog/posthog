import { DateTime } from 'luxon'

import { ParsedMessageData } from '../../session-recording/kafka/types'
import { PipelineResultType } from '../pipelines/results'
import { LibVersionMonitorStepInput, createLibVersionMonitorStep } from './lib-version-monitor-step'

describe('createLibVersionMonitorStep', () => {
    const createParsedMessage = (headers: Record<string, string>[] = []): ParsedMessageData => ({
        metadata: {
            partition: 0,
            topic: 'test-topic',
            offset: 1,
            timestamp: 1234567890,
            rawSize: 100,
        },
        headers: headers.map((h) => {
            const result: Record<string, Buffer> = {}
            for (const [key, value] of Object.entries(h)) {
                result[key] = Buffer.from(value)
            }
            return result
        }),
        distinct_id: 'distinct_id',
        session_id: 'session-1',
        token: 'test-token',
        eventsByWindowId: { window1: [] },
        eventsRange: { start: DateTime.fromMillis(0), end: DateTime.fromMillis(0) },
        snapshot_source: null,
        snapshot_library: null,
    })

    const createInput = (headers: Record<string, string>[] = []): LibVersionMonitorStepInput => ({
        parsedMessage: createParsedMessage(headers),
    })

    it('should emit warning for old lib version (< 1.75.0)', async () => {
        const step = createLibVersionMonitorStep()
        const input = createInput([{ lib_version: '1.74.0' }])

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)

        if (result.type === PipelineResultType.OK) {
            expect(result.warnings).toHaveLength(1)
            expect(result.warnings![0]).toEqual({
                type: 'replay_lib_version_too_old',
                details: {
                    libVersion: '1.74.0',
                    parsedVersion: { major: 1, minor: 74 },
                },
                key: '1.74.0',
            })
        }
    })

    it('should not emit warning for new lib version (>= 1.75.0)', async () => {
        const step = createLibVersionMonitorStep()
        const input = createInput([{ lib_version: '1.75.0' }])

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)

        if (result.type === PipelineResultType.OK) {
            expect(result.warnings ?? []).toHaveLength(0)
        }
    })

    it('should not emit warning for version 2.x', async () => {
        const step = createLibVersionMonitorStep()
        const input = createInput([{ lib_version: '2.0.0' }])

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
    })

    it('should handle invalid lib version gracefully', async () => {
        const step = createLibVersionMonitorStep()
        const input = createInput([{ lib_version: 'invalid' }])

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
    })

    it('should handle missing lib version header', async () => {
        const step = createLibVersionMonitorStep()
        const input = createInput([])

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
    })

    it('should handle version with only two parts', async () => {
        const step = createLibVersionMonitorStep()
        const input = createInput([{ lib_version: '1.74' }])

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
    })

    it('should preserve all input properties (pass-through step)', async () => {
        const step = createLibVersionMonitorStep()
        const input = createInput([{ lib_version: '1.80.0' }])

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.parsedMessage).toBe(input.parsedMessage)
        }
    })

    it('should emit warning for edge case version 1.0.0', async () => {
        const step = createLibVersionMonitorStep()
        const input = createInput([{ lib_version: '1.0.0' }])

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)

        if (result.type === PipelineResultType.OK) {
            expect(result.warnings).toHaveLength(1)
            expect(result.warnings![0].details.parsedVersion).toEqual({ major: 1, minor: 0 })
        }
    })
})
