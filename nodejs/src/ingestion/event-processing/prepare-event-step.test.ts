import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { PluginEvent } from '~/plugin-scaffold'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { createTestMessage } from '../../../tests/helpers/kafka-message'
import { createTestPerson } from '../../../tests/helpers/person'
import { createTestPluginEvent } from '../../../tests/helpers/plugin-event'
import { createTestTeam } from '../../../tests/helpers/team'
import { EventHeaders, Person, Team } from '../../types'
import { parseEventTimestamp } from '../../worker/ingestion/timestamps'
import { PipelineResultType } from '../pipelines/results'
import { createPrepareEventStep } from './prepare-event-step'
import { BLOAT_PROPERTIES } from './strip-bloat-properties'

jest.mock('../../worker/ingestion/timestamps')

type TestInput = {
    normalizedEvent: PluginEvent
    team: Team
    processPerson: boolean
    person: Person
    headers: EventHeaders
    message: Message
}

describe('createPrepareEventStep', () => {
    let mockEvent: PluginEvent
    let mockTeam: Team

    beforeEach(() => {
        jest.clearAllMocks()

        mockEvent = createTestPluginEvent({ properties: { key: 'value' } })
        mockTeam = createTestTeam()

        jest.mocked(parseEventTimestamp).mockReturnValue(DateTime.fromISO('2023-01-01T00:00:00.000Z'))
    })

    const createInput = (overrides: Partial<TestInput> = {}): TestInput => ({
        normalizedEvent: mockEvent,
        team: mockTeam,
        processPerson: true,
        person: createTestPerson(),
        headers: createTestEventHeaders(),
        message: createTestMessage(),
        ...overrides,
    })

    it.each([
        { desc: 'with processPerson=true', processPerson: true },
        { desc: 'with processPerson=false', processPerson: false },
    ])('should produce a PreIngestionEvent $desc', async ({ processPerson }) => {
        const step = createPrepareEventStep<TestInput>()
        const result = await step(createInput({ processPerson }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.preparedEvent).toEqual({
                eventUuid: mockEvent.uuid,
                event: mockEvent.event,
                distinctId: mockEvent.distinct_id,
                properties: mockEvent.properties,
                timestamp: expect.any(String),
                teamId: mockTeam.id,
                projectId: mockTeam.project_id,
            })
            expect(result.value.processPerson).toBe(processPerson)
            expect(result.value.historicalMigration).toBe(false)
        }
    })

    it.each([
        { desc: 'object event name', eventName: { foo: 'bar' }, expected: '{"foo":"bar"}' },
        { desc: 'array event name', eventName: ['event', 'list'], expected: '["event","list"]' },
        { desc: 'long event name truncated to 200 chars', eventName: 'E'.repeat(300), expected: 'E'.repeat(200) },
    ])('should sanitize event name: $desc', async ({ eventName, expected }) => {
        const event = createTestPluginEvent({ event: eventName as any })
        const step = createPrepareEventStep<TestInput>()
        const result = await step(createInput({ normalizedEvent: event }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.preparedEvent.event).toBe(expected)
        }
    })

    it('should delete $ip when team.anonymize_ips is true', async () => {
        const event = createTestPluginEvent({ properties: { $ip: '1.2.3.4', other: 'kept' } })
        const team = createTestTeam({ anonymize_ips: true })

        const step = createPrepareEventStep<TestInput>()
        const result = await step(createInput({ normalizedEvent: event, team }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.preparedEvent.properties).not.toHaveProperty('$ip')
            expect(result.value.preparedEvent.properties).toHaveProperty('other', 'kept')
        }
    })

    it.each([...BLOAT_PROPERTIES])(
        'should strip bloat property %s while preserving unrelated properties',
        async (bloatKey) => {
            const event = createTestPluginEvent({
                properties: { [bloatKey]: { heavy: 'cache-blob' }, other: 'kept' },
            })

            const step = createPrepareEventStep<TestInput>()
            const result = await step(createInput({ normalizedEvent: event }))

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.preparedEvent.properties).not.toHaveProperty(bloatKey)
                expect(result.value.preparedEvent.properties).toHaveProperty('other', 'kept')
            }
        }
    )

    it('should strip all bloat properties present in a single event', async () => {
        const bloat = Object.fromEntries([...BLOAT_PROPERTIES].map((key) => [key, { heavy: 'cache-blob' }]))
        const event = createTestPluginEvent({
            properties: { ...bloat, other: 'kept' },
        })

        const step = createPrepareEventStep<TestInput>()
        const result = await step(createInput({ normalizedEvent: event }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.preparedEvent.properties).toEqual({ other: 'kept' })
        }
    })

    it('should only strip exact matches, not substring matches', async () => {
        const event = createTestPluginEvent({
            properties: {
                ph_product_tours_foo: 'kept',
                my_ph_product_tours: 'kept',
                $product_tours_activated_at: 'kept',
                my_$override_feature_flag_payloads: 'kept',
            },
        })

        const step = createPrepareEventStep<TestInput>()
        const result = await step(createInput({ normalizedEvent: event }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.preparedEvent.properties).toHaveProperty('ph_product_tours_foo', 'kept')
            expect(result.value.preparedEvent.properties).toHaveProperty('my_ph_product_tours', 'kept')
            expect(result.value.preparedEvent.properties).toHaveProperty('$product_tours_activated_at', 'kept')
            expect(result.value.preparedEvent.properties).toHaveProperty('my_$override_feature_flag_payloads', 'kept')
        }
    })

    it.each([
        { desc: 'historical_migration=true', historical_migration: true, expected: true },
        { desc: 'historical_migration=false', historical_migration: false, expected: false },
    ])('should extract historicalMigration from headers ($desc)', async ({ historical_migration, expected }) => {
        const step = createPrepareEventStep<TestInput>()
        const result = await step(createInput({ headers: createTestEventHeaders({ historical_migration }) }))

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.historicalMigration).toBe(expected)
        }
    })

    it('should strip normalizedEvent from the output', async () => {
        const step = createPrepareEventStep<TestInput>()
        const result = await step(createInput())

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect('normalizedEvent' in result.value).toBe(false)
        }
    })

    it('should return timestamp parsing warnings as pipeline warnings', async () => {
        jest.mocked(parseEventTimestamp).mockImplementation((_event, callback) => {
            callback?.('timestamp_in_the_future', { timestamp: '3000-01-01' })
            return DateTime.fromISO('2023-01-01T00:00:00.000Z')
        })

        const step = createPrepareEventStep<TestInput>()
        const result = await step(createInput())

        expect(result.type).toBe(PipelineResultType.OK)
        expect(result.warnings).toEqual([{ type: 'timestamp_in_the_future', details: { timestamp: '3000-01-01' } }])
    })
})
