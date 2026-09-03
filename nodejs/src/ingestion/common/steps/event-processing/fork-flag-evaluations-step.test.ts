import { DateTime } from 'luxon'

import { FlagEvaluationsOutput } from '~/common/outputs'
import { MessageSizeTooLarge } from '~/common/utils/db/error'
import { parseJSON } from '~/common/utils/json-parse'
import { FlagEvaluationsService } from '~/ingestion/common/flag-evaluations/flag-evaluations-service'
import { isOkResult } from '~/ingestion/framework/results'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { ISOTimestamp, ProcessedEvent, ProjectId } from '~/types'

import { EventToEmit } from './emit-event-step'
import {
    ForkFlagEvaluationsStepInput,
    createForkFlagEvaluationsStep,
    flagEvaluationsEventsTotal,
    flagEvaluationsPendingAcks,
    flagEvaluationsSetPropsTotal,
} from './fork-flag-evaluations-step'

// Real instances: the service is a pure, synchronous config gate, so mocking
// it would only hide drift from the real class. Team 7 matches createInput.
const enabledService = () => new FlagEvaluationsService({ teams: '*', excludedTeams: [] })
const teamExcludedService = () => new FlagEvaluationsService({ teams: '*', excludedTeams: [7] })

const createStep = (service: FlagEvaluationsService) => {
    const outputs = createMockIngestionOutputs<FlagEvaluationsOutput>()
    const step = createForkFlagEvaluationsStep<ForkFlagEvaluationsStepInput>(outputs, service)
    return { step, outputs }
}

const createProcessedEvent = (overrides: Partial<ProcessedEvent> = {}): ProcessedEvent => ({
    uuid: 'event-uuid-1',
    event: '$feature_flag_called',
    properties: { $feature_flag: 'my-flag', $feature_flag_response: true },
    timestamp: '2024-01-15T10:30:00.000Z' as ISOTimestamp,
    team_id: 7,
    project_id: 7 as ProjectId,
    distinct_id: 'distinct-1',
    elements_chain: '',
    created_at: DateTime.fromISO('2024-01-15T10:31:00.000Z'),
    captured_at: null,
    person_id: 'person-uuid-1',
    person_properties: {},
    person_created_at: DateTime.fromISO('2023-01-01T00:00:00.000Z'),
    person_mode: 'full',
    ...overrides,
})

const createInput = (events: ProcessedEvent[] = [createProcessedEvent()]): ForkFlagEvaluationsStepInput => ({
    eventsToEmit: events.map((event): EventToEmit<string> => ({ event, output: 'events' })),
    teamId: 7,
})

describe('createForkFlagEvaluationsStep', () => {
    beforeEach(() => {
        flagEvaluationsEventsTotal.reset()
        flagEvaluationsSetPropsTotal.reset()
        flagEvaluationsPendingAcks.reset()
    })

    it.each([
        {
            name: 'no event is $feature_flag_called',
            buildService: () => enabledService(),
            buildInput: () => createInput([createProcessedEvent({ event: '$pageview' })]),
        },
        {
            name: 'the team is not enabled',
            buildService: () => teamExcludedService(),
            buildInput: () => createInput(),
        },
    ])('passes through without producing when $name', async ({ buildService, buildInput }) => {
        const { step, outputs } = createStep(buildService())
        const input = buildInput()

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value).toBe(input)
        }
        expect(outputs.queueMessages).not.toHaveBeenCalled()
    })

    describe('missing or invalid $feature_flag', () => {
        it.each([
            ['absent', undefined],
            ['a number', 42],
            ['an empty string', ''],
            ['null', null],
            ['an object', { nested: true }],
        ])('passes through without producing when $feature_flag is %s', async (_label, flagKey) => {
            const { step, outputs } = createStep(enabledService())
            const properties: Record<string, unknown> = { $feature_flag_response: true }
            if (flagKey !== undefined) {
                properties.$feature_flag = flagKey
            }
            const input = createInput([createProcessedEvent({ properties })])

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            expect(outputs.queueMessages).not.toHaveBeenCalled()
        })
    })

    describe('happy path', () => {
        it('produces exactly one flag_evaluations message with the narrowed events row', async () => {
            const { step, outputs } = createStep(enabledService())
            const input = createInput([
                createProcessedEvent({
                    properties: { $feature_flag: 'my-flag', $feature_flag_response: true, $set: { plan: 'pro' } },
                }),
            ])

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                // The event continues to the events table untouched, and the ack
                // rides along so the batch's offset commit waits on the produce.
                expect(result.value).toBe(input)
                expect(result.sideEffects).toHaveLength(1)
                await result.sideEffects[0]
            }
            expect(outputs.queueMessages).toHaveBeenCalledTimes(1)
            const [outputName, messages] = outputs.queueMessages.mock.calls[0]
            expect(outputName).toBe('flag_evaluations')
            expect(messages).toHaveLength(1)
            expect(messages[0].key).toBe('event-uuid-1')
            expect(messages[0].teamId).toBe(7)

            const row = parseJSON(messages[0].value!.toString())
            expect(row.event).toBe('$feature_flag_called')
            expect(row.team_id).toBe(7)
            expect(row.uuid).toBe('event-uuid-1')
            expect(row.person_id).toBe('person-uuid-1')
            expect(parseJSON(row.properties).$feature_flag).toBe('my-flag')

            // dual_written counts on the ack, not the enqueue, so it is only
            // visible after the side effect above settles.
            expect((await flagEvaluationsEventsTotal.get()).values).toContainEqual(
                expect.objectContaining({ labels: { outcome: 'dual_written' }, value: 1 })
            )
            expect((await flagEvaluationsSetPropsTotal.get()).values).toContainEqual(
                expect.objectContaining({ value: 1 })
            )
        })

        it('forks only the $feature_flag_called entry, not the $experiment_exposure duplicate', async () => {
            // create-event appends a renamed duplicate for exposure-allowlisted
            // teams; that copy belongs to the events table only.
            const { step, outputs } = createStep(enabledService())
            const original = createProcessedEvent()
            const exposureDuplicate = createProcessedEvent({ event: '$experiment_exposure', uuid: 'dup-uuid' })
            const input = createInput([original, exposureDuplicate])

            await step(input)

            expect(outputs.queueMessages).toHaveBeenCalledTimes(1)
            const [, messages] = outputs.queueMessages.mock.calls[0]
            expect(messages).toHaveLength(1)
            expect(messages[0].key).toBe('event-uuid-1')
        })
    })

    describe('mapping/produce failure isolation', () => {
        it('settles the ack rather than rejecting when the produce fails asynchronously', async () => {
            const { step, outputs } = createStep(enabledService())
            outputs.queueMessages.mockRejectedValue(new Error('produce failed'))
            const input = createInput()

            const result = await step(input)

            // A failed shadow produce must never reach the batch as a rejection.
            // See createForkFlagEvaluationsStep for why.
            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value).toBe(input)
                expect(result.sideEffects).toHaveLength(1)
                await expect(result.sideEffects[0]).resolves.toBeUndefined()
            }
            // A failed produce must never report as dual-written, and must be
            // counted rather than dropped silently.
            expect((await flagEvaluationsEventsTotal.get()).values).not.toContainEqual(
                expect.objectContaining({ labels: { outcome: 'dual_written' } })
            )
            expect((await flagEvaluationsEventsTotal.get()).values).toContainEqual(
                expect.objectContaining({ labels: { outcome: 'produce_failed' }, value: 1 })
            )
            // Settled either way, so the stall gauge must be back to zero.
            expect((await flagEvaluationsPendingAcks.get()).values[0].value).toBe(0)
        })

        it('holds the pending-acks gauge above zero while the ack has not settled', async () => {
            const { step, outputs } = createStep(enabledService())
            let settle: (() => void) | undefined
            outputs.queueMessages.mockReturnValue(
                new Promise<void>((resolve) => {
                    settle = resolve
                })
            )

            const result = await step(createInput())

            // This is the stall: the ack is neither resolved nor rejected, so no
            // outcome counter moves and only the gauge shows the fork is holding on.
            expect((await flagEvaluationsPendingAcks.get()).values[0].value).toBe(1)
            expect((await flagEvaluationsEventsTotal.get()).values).toEqual([])

            settle!()
            if (isOkResult(result)) {
                await result.sideEffects[0]
            }
            expect((await flagEvaluationsPendingAcks.get()).values[0].value).toBe(0)
        })

        it('does not block the batch when the row exceeds the broker message limit', async () => {
            const { step, outputs } = createStep(enabledService())
            outputs.queueMessages.mockRejectedValue(new MessageSizeTooLarge('too large', new Error('too large')))
            const input = createInput()

            const result = await step(input)

            // An oversized row gets its own outcome and no warning, because
            // retrying or alerting on it would change nothing.
            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                await expect(result.sideEffects[0]).resolves.toBeUndefined()
            }
            expect((await flagEvaluationsEventsTotal.get()).values).toContainEqual(
                expect.objectContaining({ labels: { outcome: 'continued_message_too_large' }, value: 1 })
            )
            expect((await flagEvaluationsPendingAcks.get()).values[0].value).toBe(0)
        })

        it('still returns ok(input) with no ack side effect when queueMessages throws synchronously', async () => {
            const { step, outputs } = createStep(enabledService())
            outputs.queueMessages.mockImplementation(() => {
                throw new Error('sync produce failure')
            })
            const input = createInput([
                createProcessedEvent({ uuid: 'event-uuid-1' }),
                createProcessedEvent({ uuid: 'event-uuid-2', properties: { $feature_flag_response: true } }),
            ])

            const result = await step(input)

            // The fork must never block the events path: a failure here is
            // swallowed, not surfaced as a DLQ/drop result.
            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value).toBe(input)
                expect(result.sideEffects).toHaveLength(0)
            }
            // One outcome per event: the invalid-key event is already counted, so
            // continued_fork_error covers only the remaining one.
            expect((await flagEvaluationsEventsTotal.get()).values).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({ labels: { outcome: 'continued_invalid_flag_key' }, value: 1 }),
                    expect.objectContaining({ labels: { outcome: 'continued_fork_error' }, value: 1 }),
                ])
            )
        })
    })
})
