import { DateTime } from 'luxon'

import { createTestPerson } from '../../../tests/helpers/person'
import { createTestPluginEvent } from '../../../tests/helpers/plugin-event'
import { createTestTeam } from '../../../tests/helpers/team'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Person } from '../../types'
import * as processPersonsStepModule from '../../worker/ingestion/event-pipeline/processPersonsStep'
import { EventPipelineRunnerOptions } from '../../worker/ingestion/event-pipeline/runner'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResultType, dlq, ok } from '../pipelines/results'
import { createProcessPersonsStep } from './process-persons-step'

jest.mock('../../worker/ingestion/event-pipeline/processPersonsStep')

const mockProcessPersonsStep = jest.mocked(processPersonsStepModule.processPersonsStep)

const fakePerson = createTestPerson()

const createTestInput = (overrides: Record<string, unknown> = {}) => ({
    normalizedEvent: createTestPluginEvent(),
    team: createTestTeam(),
    timestamp: DateTime.fromISO('2020-02-23T02:15:00Z', { zone: 'utc' }),
    ...overrides,
})

const mockOptions: EventPipelineRunnerOptions = {
    SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: false,
    TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE: 0,
    PIPELINE_STEP_STALLED_LOG_TIMEOUT: 30000,
    PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: 100,
    PERSON_MERGE_ASYNC_ENABLED: false,
    PERSON_MERGE_ASYNC_TOPIC: '',
    PERSON_MERGE_SYNC_BATCH_SIZE: 1,
    PERSON_JSONB_SIZE_ESTIMATE_ENABLE: 0,
    PERSON_PROPERTIES_UPDATE_ALL: false,
}
const mockKafkaProducer = {} as KafkaProducerWrapper
const mockPersonsStore = {} as PersonsStore

describe('createProcessPersonsStep', () => {
    beforeEach(() => {
        jest.resetAllMocks()
    })

    it('calls processPersonsStep when no personlessPerson is provided', async () => {
        const ack = Promise.resolve()
        const processedEvent = createTestPluginEvent({ event: 'processed' })
        mockProcessPersonsStep.mockResolvedValue(ok([processedEvent, fakePerson, ack]))

        const step = createProcessPersonsStep(mockOptions, mockKafkaProducer, mockPersonsStore)
        const input = createTestInput()

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        expect(mockProcessPersonsStep).toHaveBeenCalledTimes(1)
        expect(mockProcessPersonsStep).toHaveBeenCalledWith(
            mockKafkaProducer,
            expect.any(Object),
            mockOptions.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
            mockOptions.PERSON_PROPERTIES_UPDATE_ALL,
            input.normalizedEvent,
            input.team,
            input.timestamp,
            true,
            mockPersonsStore
        )
        if (result.type === PipelineResultType.OK) {
            expect(result.value.person).toBe(fakePerson)
            expect(result.value.normalizedEvent).toBe(processedEvent)
            expect(result.sideEffects).toEqual([ack])
        }
    })

    it('skips processPersonsStep when personlessPerson is provided without force_upgrade', async () => {
        const step = createProcessPersonsStep(mockOptions, mockKafkaProducer, mockPersonsStore)
        const personlessPerson: Person = { ...fakePerson, force_upgrade: false }
        const input = createTestInput({ personlessPerson })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        expect(mockProcessPersonsStep).not.toHaveBeenCalled()
        if (result.type === PipelineResultType.OK) {
            expect(result.value.person).toBe(personlessPerson)
            expect(result.sideEffects).toEqual([])
        }
    })

    it('calls processPersonsStep when personlessPerson has force_upgrade', async () => {
        const ack = Promise.resolve()
        const processedEvent = createTestPluginEvent({ event: 'processed' })
        const processedPerson: Person = { ...fakePerson, properties: { upgraded: true } }
        mockProcessPersonsStep.mockResolvedValue(ok([processedEvent, processedPerson, ack]))

        const step = createProcessPersonsStep(mockOptions, mockKafkaProducer, mockPersonsStore)
        const personlessPerson: Person = { ...fakePerson, force_upgrade: true }
        const input = createTestInput({ personlessPerson })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        expect(mockProcessPersonsStep).toHaveBeenCalledTimes(1)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.person.force_upgrade).toBe(true)
            expect(result.value.normalizedEvent).toBe(processedEvent)
            expect(result.sideEffects).toEqual([ack])
        }
    })

    it('preserves all input fields in the output', async () => {
        mockProcessPersonsStep.mockResolvedValue(ok([createTestPluginEvent(), fakePerson, Promise.resolve()]))

        const step = createProcessPersonsStep(mockOptions, mockKafkaProducer, mockPersonsStore)
        const input = { ...createTestInput(), extraField: 'preserved' }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect((result.value as any).extraField).toBe('preserved')
            expect(result.value.team).toBe(input.team)
            expect(result.value.timestamp).toBe(input.timestamp)
        }
    })

    it('propagates non-ok results from processPersonsStep', async () => {
        mockProcessPersonsStep.mockResolvedValue(dlq('db error', new Error('connection failed')))

        const step = createProcessPersonsStep(mockOptions, mockKafkaProducer, mockPersonsStore)
        const input = createTestInput()

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (result.type === PipelineResultType.DLQ) {
            expect(result.reason).toBe('db error')
        }
    })
})
