import { DateTime } from 'luxon'

import { createTestPerson } from '../../../tests/helpers/person'
import { createTestPluginEvent } from '../../../tests/helpers/plugin-event'
import { createTestTeam } from '../../../tests/helpers/team'
import { KAFKA_PERSON } from '../../config/kafka-topics'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { parseJSON } from '../../utils/json-parse'
import { uuidFromDistinctId } from '../../worker/ingestion/person-uuid'
import { PropertyUpdates } from '../../worker/ingestion/persons/person-update'
import { isOkResult } from '../pipelines/results'
import { createTestingPublishPersonUpdateStep } from './testing-publish-person-update-step'

describe('testing-publish-person-update-step', () => {
    let mockKafkaProducer: jest.Mocked<Pick<KafkaProducerWrapper, 'queueMessages'>>

    const team = createTestTeam()

    beforeEach(() => {
        mockKafkaProducer = {
            queueMessages: jest.fn().mockResolvedValue(undefined),
        }
    })

    const noChanges: PropertyUpdates = { hasChanges: false, toSet: {}, toUnset: [], shouldForceUpdate: false }
    const withChanges: PropertyUpdates = {
        hasChanges: true,
        toSet: { name: 'Alice' },
        toUnset: [],
        shouldForceUpdate: false,
    }

    function parseKafkaPersonMessage() {
        const kafkaMessage = mockKafkaProducer.queueMessages.mock.calls[0][0]
        expect(kafkaMessage).toMatchObject({ topic: KAFKA_PERSON })
        return parseJSON((kafkaMessage as any).messages[0].value)
    }

    describe('no person found (approximates person creation)', () => {
        it('creates a fake person with $set/$set_once properties and publishes', async () => {
            const step = createTestingPublishPersonUpdateStep(mockKafkaProducer as unknown as KafkaProducerWrapper)
            const event = createTestPluginEvent({
                distinct_id: 'new-user',
                properties: { $set: { name: 'Alice' }, $set_once: { role: 'admin' } },
            })
            const result = await step({ normalizedEvent: event, team, person: undefined })

            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.person).toEqual({
                team_id: team.id,
                properties: { role: 'admin', name: 'Alice' },
                uuid: uuidFromDistinctId(team.id, 'new-user'),
                created_at: DateTime.utc(1970, 1, 1, 0, 0, 5),
            })
            expect(mockKafkaProducer.queueMessages).toHaveBeenCalledTimes(1)
            expect(result.sideEffects).toHaveLength(1)
        })

        it('$set overwrites $set_once for same key', async () => {
            const step = createTestingPublishPersonUpdateStep(mockKafkaProducer as unknown as KafkaProducerWrapper)
            const event = createTestPluginEvent({
                distinct_id: 'new-user',
                properties: { $set: { name: 'Bob' }, $set_once: { name: 'Alice' } },
            })
            const result = await step({ normalizedEvent: event, team, person: undefined })

            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }
            expect(result.value.person.properties).toEqual({ name: 'Bob' })
        })

        it('publishes even with no $set/$set_once properties', async () => {
            const step = createTestingPublishPersonUpdateStep(mockKafkaProducer as unknown as KafkaProducerWrapper)
            const event = createTestPluginEvent({ distinct_id: 'new-user', properties: {} })
            const result = await step({ normalizedEvent: event, team, person: undefined })

            expect(isOkResult(result)).toBe(true)
            expect(mockKafkaProducer.queueMessages).toHaveBeenCalledTimes(1)
        })

        it('Kafka message contains the fake person with applied properties', async () => {
            const step = createTestingPublishPersonUpdateStep(mockKafkaProducer as unknown as KafkaProducerWrapper)
            const event = createTestPluginEvent({
                distinct_id: 'new-user',
                properties: { $set: { name: 'Alice' } },
            })
            await step({ normalizedEvent: event, team, person: undefined })

            const messageValue = parseKafkaPersonMessage()
            expect(messageValue.id).toBe(uuidFromDistinctId(team.id, 'new-user'))
            expect(parseJSON(messageValue.properties)).toEqual({ name: 'Alice' })
        })
    })

    describe('person found with property changes', () => {
        it('publishes a Kafka message when personPropertyUpdates has changes', async () => {
            const person = createTestPerson({ uuid: 'person-uuid-abc', properties: { name: 'Alice' } })
            const event = createTestPluginEvent()

            const step = createTestingPublishPersonUpdateStep(mockKafkaProducer as unknown as KafkaProducerWrapper)
            const result = await step({
                normalizedEvent: event,
                team,
                person,
                personPropertyUpdates: withChanges,
            })

            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(mockKafkaProducer.queueMessages).toHaveBeenCalledTimes(1)
            expect(result.sideEffects).toHaveLength(1)
        })

        it('Kafka message contains the merged person properties', async () => {
            const person = createTestPerson({
                uuid: 'person-uuid-abc',
                properties: { existing: 'value', newProp: 'hello' },
            })
            const event = createTestPluginEvent()

            const step = createTestingPublishPersonUpdateStep(mockKafkaProducer as unknown as KafkaProducerWrapper)
            await step({
                normalizedEvent: event,
                team,
                person,
                personPropertyUpdates: withChanges,
            })

            const messageValue = parseKafkaPersonMessage()
            expect(messageValue.id).toBe('person-uuid-abc')
            expect(parseJSON(messageValue.properties)).toEqual({ existing: 'value', newProp: 'hello' })
        })

        it('returns the same person reference', async () => {
            const person = createTestPerson({ properties: { name: 'Alice' } })
            const event = createTestPluginEvent()

            const step = createTestingPublishPersonUpdateStep(mockKafkaProducer as unknown as KafkaProducerWrapper)
            const result = await step({
                normalizedEvent: event,
                team,
                person,
                personPropertyUpdates: withChanges,
            })

            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }
            expect(result.value.person).toBe(person)
        })
    })

    describe('identify events (approximates is_identified update)', () => {
        it.each(['$identify', '$create_alias', '$merge_dangerously'])(
            'publishes for %s even without property changes',
            async (eventName) => {
                const person = createTestPerson({ uuid: 'person-uuid' })
                const event = createTestPluginEvent({ event: eventName })

                const step = createTestingPublishPersonUpdateStep(mockKafkaProducer as unknown as KafkaProducerWrapper)
                const result = await step({
                    normalizedEvent: event,
                    team,
                    person,
                    personPropertyUpdates: noChanges,
                })

                expect(isOkResult(result)).toBe(true)
                expect(mockKafkaProducer.queueMessages).toHaveBeenCalledTimes(1)
            }
        )

        it('sets is_identified=true in the Kafka message for identify events', async () => {
            const person = createTestPerson({ uuid: 'person-uuid' })
            const event = createTestPluginEvent({ event: '$identify' })

            const step = createTestingPublishPersonUpdateStep(mockKafkaProducer as unknown as KafkaProducerWrapper)
            await step({
                normalizedEvent: event,
                team,
                person,
                personPropertyUpdates: noChanges,
            })

            const messageValue = parseKafkaPersonMessage()
            expect(messageValue.is_identified).toBe(1)
        })
    })

    describe('no changes', () => {
        it('does not publish when no property changes and not an identify event', async () => {
            const person = createTestPerson({ properties: { email: 'test@example.com' } })
            const event = createTestPluginEvent()

            const step = createTestingPublishPersonUpdateStep(mockKafkaProducer as unknown as KafkaProducerWrapper)
            const result = await step({
                normalizedEvent: event,
                team,
                person,
                personPropertyUpdates: noChanges,
            })

            expect(isOkResult(result)).toBe(true)
            if (!isOkResult(result)) {
                return
            }

            expect(result.value.person).toBe(person)
            expect(mockKafkaProducer.queueMessages).not.toHaveBeenCalled()
            expect(result.sideEffects).toEqual([])
        })

        it('does not publish when personPropertyUpdates is undefined and not an identify event', async () => {
            const person = createTestPerson()
            const event = createTestPluginEvent()

            const step = createTestingPublishPersonUpdateStep(mockKafkaProducer as unknown as KafkaProducerWrapper)
            const result = await step({ normalizedEvent: event, team, person })

            expect(isOkResult(result)).toBe(true)
            expect(mockKafkaProducer.queueMessages).not.toHaveBeenCalled()
        })
    })

    it('passes through extra input fields unchanged', async () => {
        const person = createTestPerson()
        const event = createTestPluginEvent()
        const extraField = { someExtraData: 'preserved' }

        const step = createTestingPublishPersonUpdateStep(mockKafkaProducer as unknown as KafkaProducerWrapper)
        const result = await step({ normalizedEvent: event, team, person, ...extraField })

        expect(isOkResult(result)).toBe(true)
        if (!isOkResult(result)) {
            return
        }
        expect((result.value as any).someExtraData).toBe('preserved')
    })
})
