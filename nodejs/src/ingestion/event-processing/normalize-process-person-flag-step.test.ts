import { v4 } from 'uuid'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { createTestMessage } from '../../../tests/helpers/kafka-message'
import { createTestPluginEvent } from '../../../tests/helpers/plugin-event'
import { createTestTeam } from '../../../tests/helpers/team'
import { PerDistinctIdPipelineInput } from '../analytics'
import { PipelineResultType } from '../pipelines/results'
import { createNormalizeProcessPersonFlagStep } from './normalize-process-person-flag-step'

describe('normalizeProcessPersonFlagStep', () => {
    const team = createTestTeam()

    const baseEvent: PluginEvent = createTestPluginEvent({
        distinct_id: 'my_id',
        site_url: '',
        team_id: 1,
        now: new Date().toISOString(),
        uuid: v4(),
    })

    const baseInput: PerDistinctIdPipelineInput = {
        message: createTestMessage(),
        event: baseEvent,
        team,
        headers: createTestEventHeaders(),
        groupStoreForBatch: {} as any,
    }

    const normalizeStep = createNormalizeProcessPersonFlagStep()

    describe('$process_person_profile=false', () => {
        it.each(['$identify', '$create_alias', '$merge_dangerously', '$groupidentify'])(
            'drops event %s when $process_person_profile=false',
            async (eventName) => {
                const input: PerDistinctIdPipelineInput = {
                    ...baseInput,
                    event: {
                        ...baseEvent,
                        event: eventName,
                        properties: { $process_person_profile: false },
                    },
                }

                const result = await normalizeStep(input)

                expect(result.type).toBe(PipelineResultType.DROP)
                expect(result.warnings).toHaveLength(1)
                expect(result.warnings[0]).toMatchObject({
                    type: 'invalid_event_when_process_person_profile_is_false',
                    details: {
                        eventUuid: baseEvent.uuid,
                        event: eventName,
                        distinctId: 'my_id',
                    },
                    alwaysSend: true,
                })
            }
        )

        it('allows regular events when $process_person_profile=false', async () => {
            const input: PerDistinctIdPipelineInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$pageview',
                    properties: { $process_person_profile: false },
                },
            }

            const result = await normalizeStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.processPerson).toBe(false)
                expect(result.value.forceDisablePersonProcessing).toBe(false)
            }
        })

        it('adds warning for invalid $process_person_profile values', async () => {
            const input: PerDistinctIdPipelineInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    properties: { $process_person_profile: 'invalid' },
                },
            }

            const result = await normalizeStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.warnings).toHaveLength(1)
            expect(result.warnings[0]).toMatchObject({
                type: 'invalid_process_person_profile',
                details: {
                    eventUuid: baseEvent.uuid,
                    event: baseEvent.event,
                    distinctId: 'my_id',
                    $process_person_profile: 'invalid',
                    message: 'Only a boolean value is valid for the $process_person_profile property',
                },
                alwaysSend: false,
            })
        })
    })

    describe('force_disable_person_processing header', () => {
        it('sets processPerson to false when header is true', async () => {
            const input: PerDistinctIdPipelineInput = {
                ...baseInput,
                headers: createTestEventHeaders({ force_disable_person_processing: true }),
            }

            const result = await normalizeStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.processPerson).toBe(false)
                expect(result.value.forceDisablePersonProcessing).toBe(true)
            }
        })

        it('defaults to processPerson=true when header is false and no $process_person_profile property', async () => {
            const input: PerDistinctIdPipelineInput = {
                ...baseInput,
                headers: createTestEventHeaders(),
            }

            const result = await normalizeStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.processPerson).toBe(true)
                expect(result.value.forceDisablePersonProcessing).toBe(false)
            }
        })

        it('overrides $process_person_profile property when header is true', async () => {
            const input: PerDistinctIdPipelineInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    properties: { $process_person_profile: true },
                },
                headers: createTestEventHeaders({ force_disable_person_processing: true }),
            }

            const result = await normalizeStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.processPerson).toBe(false)
                expect(result.value.forceDisablePersonProcessing).toBe(true)
            }
        })

        it('respects $process_person_profile=false when header is false', async () => {
            const input: PerDistinctIdPipelineInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    properties: { $process_person_profile: false },
                },
                headers: createTestEventHeaders(),
            }

            const result = await normalizeStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.processPerson).toBe(false)
                expect(result.value.forceDisablePersonProcessing).toBe(false)
            }
        })
    })

    describe('default behavior', () => {
        it('defaults to processPerson=true when no header and no $process_person_profile property', async () => {
            const input: PerDistinctIdPipelineInput = {
                ...baseInput,
            }

            const result = await normalizeStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.processPerson).toBe(true)
                expect(result.value.forceDisablePersonProcessing).toBe(false)
            }
        })

        it('keeps processPerson=true when $process_person_profile=true explicitly', async () => {
            const input: PerDistinctIdPipelineInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    properties: { $process_person_profile: true },
                },
            }

            const result = await normalizeStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.processPerson).toBe(true)
                expect(result.value.forceDisablePersonProcessing).toBe(false)
            }
        })
    })
})
