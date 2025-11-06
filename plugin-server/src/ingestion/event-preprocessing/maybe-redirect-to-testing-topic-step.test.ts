import { Message } from 'node-rdkafka'

import { PipelineResultType } from '../pipelines/results'
import { createMaybeRedirectToTestingTopicStep } from './maybe-redirect-to-testing-topic-step'

describe('createMaybeRedirectToTestingTopicStep', () => {
    const mockMessage: Message = {
        value: Buffer.from('test'),
        size: 4,
        topic: 'events_plugin_ingestion',
        offset: 1,
        partition: 0,
        key: null,
        timestamp: Date.now(),
    }

    it('should return ok when no testing topic is configured', async () => {
        const step = createMaybeRedirectToTestingTopicStep(null)
        const input = { message: mockMessage }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value).toEqual(input)
        }
    })

    it('should redirect to testing topic when configured', async () => {
        const testingTopic = 'events_plugin_ingestion_test'
        const step = createMaybeRedirectToTestingTopicStep(testingTopic)
        const input = { message: mockMessage }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.REDIRECT)
        if (result.type === PipelineResultType.REDIRECT) {
            expect(result.reason).toBe('testing_topic')
            expect(result.topic).toBe(testingTopic)
            expect(result.preserveKey).toBe(true)
            expect(result.awaitAck).toBe(true)
        }
    })

    it('should preserve input structure in redirect', async () => {
        const testingTopic = 'events_plugin_ingestion_test'
        const step = createMaybeRedirectToTestingTopicStep(testingTopic)
        const input = {
            message: mockMessage,
            additionalField: 'some data',
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.REDIRECT)
    })
})
