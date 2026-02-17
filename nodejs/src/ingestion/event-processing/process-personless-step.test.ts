import { DateTime } from 'luxon'

import { createTestPluginEvent } from '../../../tests/helpers/plugin-event'
import { createTestTeam } from '../../../tests/helpers/team'
import { Person } from '../../types'
import * as processPersonlessStepModule from '../../worker/ingestion/event-pipeline/processPersonlessStep'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResultType, dlq, ok } from '../pipelines/results'
import { createProcessPersonlessStep } from './process-personless-step'

jest.mock('../../worker/ingestion/event-pipeline/processPersonlessStep')

const mockProcessPersonlessStep = jest.mocked(processPersonlessStepModule.processPersonlessStep)

const fakePerson: Person = {
    team_id: 1,
    properties: {},
    uuid: 'fake-person-uuid',
    created_at: DateTime.utc(1970, 1, 1, 0, 0, 5),
}

const createTestInput = (overrides: Record<string, unknown> = {}) => ({
    normalizedEvent: createTestPluginEvent(),
    team: createTestTeam(),
    timestamp: DateTime.fromISO('2020-02-23T02:15:00Z', { zone: 'utc' }),
    processPerson: false,
    forceDisablePersonProcessing: false,
    ...overrides,
})

describe('createProcessPersonlessStep', () => {
    const personsStore = {} as PersonsStore

    beforeEach(() => {
        jest.resetAllMocks()
    })

    it('passes through when processPerson is true', async () => {
        const step = createProcessPersonlessStep(personsStore)
        const input = createTestInput({ processPerson: true })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        expect(mockProcessPersonlessStep).not.toHaveBeenCalled()
        if (result.type === PipelineResultType.OK) {
            expect(result.value.personlessPerson).toBeUndefined()
        }
    })

    it('calls processPersonlessStep and returns person when processPerson is false', async () => {
        mockProcessPersonlessStep.mockResolvedValue(ok(fakePerson))

        const step = createProcessPersonlessStep(personsStore)
        const input = createTestInput()

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.personlessPerson).toBe(fakePerson)
        }
    })

    it('passes correct arguments to underlying step', async () => {
        mockProcessPersonlessStep.mockResolvedValue(ok(fakePerson))

        const step = createProcessPersonlessStep(personsStore)
        const input = createTestInput({ forceDisablePersonProcessing: true })

        await step(input)

        expect(mockProcessPersonlessStep).toHaveBeenCalledWith(
            input.normalizedEvent,
            input.team,
            input.timestamp,
            personsStore,
            true
        )
    })

    it('preserves all input fields in the output', async () => {
        mockProcessPersonlessStep.mockResolvedValue(ok(fakePerson))

        const step = createProcessPersonlessStep(personsStore)
        const input = { ...createTestInput(), extraField: 'preserved' }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.normalizedEvent).toBe(input.normalizedEvent)
            expect(result.value.team).toBe(input.team)
            expect(result.value.timestamp).toBe(input.timestamp)
            expect((result.value as any).extraField).toBe('preserved')
        }
    })

    it('propagates non-ok results unchanged', async () => {
        const dlqResult = dlq<Person>('something went wrong', new Error('db error'))
        mockProcessPersonlessStep.mockResolvedValue(dlqResult)

        const step = createProcessPersonlessStep(personsStore)
        const input = createTestInput()

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (result.type === PipelineResultType.DLQ) {
            expect(result.reason).toBe('something went wrong')
        }
    })
})
