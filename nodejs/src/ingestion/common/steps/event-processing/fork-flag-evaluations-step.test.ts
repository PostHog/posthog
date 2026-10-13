import { DateTime } from 'luxon'

import { FlagEvaluationsOutput, IngestionWarningsOutput, RealtimeOnlyEventsOutput } from '~/common/outputs'
import { MessageSizeTooLarge } from '~/common/utils/db/error'
import { parseJSON } from '~/common/utils/json-parse'
import { FlagEvaluationsService } from '~/ingestion/common/flag-evaluations/flag-evaluations-service'
import { isOkResult } from '~/ingestion/framework/results'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { FlagEvaluationsMode, ISOTimestamp, ProcessedEvent, ProjectId } from '~/types'

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
const enabledService = ({
    excludedTeams = [] as number[],
    flagEvaluationsOnlyDisabled = false,
    routesToRealtimeOnlyEvents = true,
} = {}) =>
    new FlagEvaluationsService({ teams: '*', excludedTeams, flagEvaluationsOnlyDisabled, routesToRealtimeOnlyEvents })

const createStep = (service: FlagEvaluationsService) => {
    const outputs = createMockIngestionOutputs<
        FlagEvaluationsOutput | IngestionWarningsOutput | RealtimeOnlyEventsOutput
    >()
    const step = createForkFlagEvaluationsStep<ForkFlagEvaluationsStepInput>(outputs, service)
    return { step, outputs }
}

type StepDeps = ReturnType<typeof createStep>

const createProcessedEvent = (overrides: Partial<ProcessedEvent> = {}): ProcessedEvent => ({
    uuid: 'event-uuid-1',
    event: '$feature_flag_called',
    properties: { $feature_flag: 'my-flag', $feature_flag_response: true },
    timestamp: DateTime.utc().minus({ hours: 1 }).toISO() as ISOTimestamp,
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

// create-event appends this renamed copy of a multivariate flag call for
// exposure-allowlisted teams. The copy belongs to the events table only.
const createExposureDuplicate = (): ProcessedEvent =>
    createProcessedEvent({ event: '$experiment_exposure', uuid: 'dup-uuid' })

const createInput = (
    events: ProcessedEvent[] = [createProcessedEvent()],
    mode: FlagEvaluationsMode = FlagEvaluationsMode.Events
): ForkFlagEvaluationsStepInput => ({
    eventsToEmit: events.map((event): EventToEmit<string> => ({ event, output: 'events' })),
    teamId: 7,
    team: { flag_evaluations_mode: mode },
})

const emitted = (eventsToEmit: EventToEmit<string>[]) =>
    eventsToEmit.map(({ event, output }) => ({ uuid: event.uuid, output }))

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
            buildService: () => enabledService({ excludedTeams: [7] }),
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
            const { step, outputs } = createStep(enabledService())
            const input = createInput([createProcessedEvent(), createExposureDuplicate()])

            await step(input)

            expect(outputs.queueMessages).toHaveBeenCalledTimes(1)
            const [, messages] = outputs.queueMessages.mock.calls[0]
            expect(messages).toHaveLength(1)
            expect(messages[0].key).toBe('event-uuid-1')
        })
    })

    describe('flag_evaluations retention', () => {
        afterEach(() => {
            jest.useRealTimers()
        })

        it.each([
            // 2026-07-05 is the oldest UTC day a 90-day TTL keeps on 2026-10-02.
            { timestamp: '2026-07-04T23:59:59.999Z', forked: false, outcome: 'continued_past_retention' },
            { timestamp: '2026-07-05T00:00:00.000Z', forked: true, outcome: 'dual_written' },
        ])('forks a call dated $timestamp -> $forked', async ({ timestamp, forked, outcome }) => {
            jest.useFakeTimers({ now: new Date('2026-10-02T15:00:00.000Z') })
            const { step, outputs } = createStep(enabledService())

            const result = await step(createInput([createProcessedEvent({ timestamp: timestamp as ISOTimestamp })]))

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                await Promise.all(result.sideEffects)
            }
            expect(outputs.queueMessages).toHaveBeenCalledTimes(forked ? 1 : 0)
            expect((await flagEvaluationsEventsTotal.get()).values).toEqual([
                expect.objectContaining({ labels: { outcome }, value: 1 }),
            ])
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

        // An oversized row gets its own outcome and no log warning, because
        // retrying or alerting on it would change nothing. A FLAG_EVALUATIONS_ONLY
        // team has no events row to carry emit-event's oversize warning, so the
        // fork sends that ingestion warning instead.
        it.each([
            {
                name: 'an EVENTS',
                mode: FlagEvaluationsMode.Events,
                outcome: 'continued_message_too_large',
                producedOutputs: ['flag_evaluations'],
                warnings: [],
            },
            {
                name: 'a FLAG_EVALUATIONS_ONLY',
                mode: FlagEvaluationsMode.FlagEvaluationsOnly,
                routesToRealtimeOnlyEvents: false,
                outcome: 'lost_message_too_large',
                producedOutputs: ['flag_evaluations', 'ingestion_warnings'],
                warnings: [{ type: 'message_size_too_large', eventUuid: 'event-uuid-1' }],
            },
            {
                name: 'a routed FLAG_EVALUATIONS_ONLY',
                mode: FlagEvaluationsMode.FlagEvaluationsOnly,
                routesToRealtimeOnlyEvents: true,
                outcome: 'lost_message_too_large',
                producedOutputs: ['flag_evaluations'],
                warnings: [],
            },
        ])(
            'does not block the batch when the row exceeds the broker message limit for $name team',
            async ({ mode, routesToRealtimeOnlyEvents, outcome, producedOutputs, warnings }) => {
                const { step, outputs } = createStep(enabledService({ routesToRealtimeOnlyEvents }))
                outputs.queueMessages.mockRejectedValueOnce(
                    new MessageSizeTooLarge('too large', new Error('too large'))
                )
                const input = createInput([createProcessedEvent()], mode)

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                if (isOkResult(result)) {
                    await result.sideEffects[0]
                }
                expect((await flagEvaluationsEventsTotal.get()).values).toEqual([
                    expect.objectContaining({ labels: { outcome }, value: 1 }),
                ])
                expect(outputs.queueMessages.mock.calls.map(([output]) => output)).toEqual(producedOutputs)
                const sentWarnings = outputs.queueMessages.mock.calls
                    .filter(([output]) => output === 'ingestion_warnings')
                    .flatMap(([, messages]) => messages.map((message) => parseJSON(message.value!.toString())))
                    .map((warning) => ({ type: warning.type, eventUuid: parseJSON(warning.details).eventUuid }))
                expect(sentWarnings).toEqual(warnings)
                expect((await flagEvaluationsPendingAcks.get()).values[0].value).toBe(0)
            }
        )

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

    describe('FLAG_EVALUATIONS_ONLY mode', () => {
        it.each([
            {
                name: 'removes the queued $feature_flag_called event from eventsToEmit',
                routesToRealtimeOnlyEvents: false,
                expectedEventsToEmit: [{ uuid: 'dup-uuid', output: 'events' }],
            },
            {
                name: 'sends the queued $feature_flag_called event to the realtime_only_events output',
                routesToRealtimeOnlyEvents: true,
                expectedEventsToEmit: [
                    { uuid: 'event-uuid-1', output: 'realtime_only_events' },
                    { uuid: 'dup-uuid', output: 'events' },
                ],
            },
        ])(
            '$name and keeps the $experiment_exposure copy on events',
            async ({ routesToRealtimeOnlyEvents, expectedEventsToEmit }) => {
                const { step, outputs } = createStep(enabledService({ routesToRealtimeOnlyEvents }))
                const input = createInput(
                    [createProcessedEvent(), createExposureDuplicate()],
                    FlagEvaluationsMode.FlagEvaluationsOnly
                )

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                if (isOkResult(result)) {
                    expect(emitted(result.value.eventsToEmit)).toEqual(expectedEventsToEmit)
                    await Promise.all(result.sideEffects)
                }
                // For a FLAG_EVALUATIONS_ONLY team the flag_evaluations row is the only stored copy of the call.
                expect(outputs.queueMessages).toHaveBeenCalledTimes(1)
                expect(outputs.queueMessages.mock.calls[0][1].map((message) => message.key)).toEqual(['event-uuid-1'])
                // The counter records one outcome per event, so the call must not also count as dual_written.
                expect((await flagEvaluationsEventsTotal.get()).values).toEqual([
                    expect.objectContaining({ labels: { outcome: 'flag_evaluations_only' }, value: 1 }),
                ])
            }
        )

        it.each([
            {
                name: 'the mode is EVENTS',
                mode: FlagEvaluationsMode.Events,
                buildService: () => enabledService(),
            },
            {
                name: 'the mode is READ_FLAG_EVALUATIONS',
                mode: FlagEvaluationsMode.ReadFlagEvaluations,
                buildService: () => enabledService(),
            },
            {
                name: 'INGESTION_FLAG_EVALUATIONS_ONLY_DISABLED is on',
                mode: FlagEvaluationsMode.FlagEvaluationsOnly,
                buildService: () => enabledService({ flagEvaluationsOnlyDisabled: true }),
            },
            {
                name: 'the team is not enabled',
                mode: FlagEvaluationsMode.FlagEvaluationsOnly,
                buildService: () => enabledService({ excludedTeams: [7] }),
            },
            {
                name: 'the flag key is missing',
                mode: FlagEvaluationsMode.FlagEvaluationsOnly,
                buildService: () => enabledService(),
                flagCalledOverrides: { properties: { $feature_flag_response: true } },
            },
            {
                name: 'the call is past the flag_evaluations retention',
                mode: FlagEvaluationsMode.FlagEvaluationsOnly,
                buildService: () => enabledService(),
                flagCalledOverrides: { timestamp: DateTime.utc().minus({ days: 91 }).toISO() as ISOTimestamp },
            },
            {
                name: 'queueing the row throws',
                mode: FlagEvaluationsMode.FlagEvaluationsOnly,
                buildService: () => enabledService(),
                arrange: ({ outputs }: StepDeps) =>
                    outputs.queueMessages.mockImplementation(() => {
                        throw new Error('sync produce failure')
                    }),
            },
        ])(
            'keeps the $feature_flag_called event on the events output when $name',
            async ({ mode, buildService, flagCalledOverrides, arrange }) => {
                const deps = createStep(buildService())
                arrange?.(deps)
                const input = createInput([createProcessedEvent(flagCalledOverrides), createExposureDuplicate()], mode)

                const result = await deps.step(input)

                expect(isOkResult(result)).toBe(true)
                if (isOkResult(result)) {
                    expect(emitted(result.value.eventsToEmit)).toEqual([
                        { uuid: 'event-uuid-1', output: 'events' },
                        { uuid: 'dup-uuid', output: 'events' },
                    ])
                    await Promise.all(result.sideEffects)
                }
                expect((await flagEvaluationsEventsTotal.get()).values).not.toContainEqual(
                    expect.objectContaining({ labels: { outcome: 'flag_evaluations_only' } })
                )
            }
        )
    })
})
