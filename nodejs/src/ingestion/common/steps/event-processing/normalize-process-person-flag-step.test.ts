import { v4 } from 'uuid'

import { PipelineResultType } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'
import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { EventHeaders } from '~/types'

import { createNormalizeProcessPersonFlagStep } from './normalize-process-person-flag-step'

type StepInput = { event: PluginEvent; headers: EventHeaders }

describe('normalizeProcessPersonFlagStep', () => {
    const baseEvent: PluginEvent = createTestPluginEvent({
        distinct_id: 'my_id',
        site_url: '',
        team_id: 1,
        now: new Date().toISOString(),
        uuid: v4(),
    })

    const baseInput: StepInput = {
        event: baseEvent,
        headers: createTestEventHeaders(),
    }

    const normalizeStep = createNormalizeProcessPersonFlagStep()

    describe('$process_person_profile=false', () => {
        it.each(['$identify', '$create_alias', '$merge_dangerously', '$groupidentify'])(
            'drops event %s when $process_person_profile=false',
            async (eventName) => {
                const input: StepInput = {
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
            const input: StepInput = {
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
                expect(result.value.processPersonExplicitlyTrue).toBe(false)
                expect(result.value.forceDisablePersonProcessing).toBe(false)
            }
        })

        it('adds warning for invalid $process_person_profile values', async () => {
            const input: StepInput = {
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
            const input: StepInput = {
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
            const input: StepInput = {
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
            const input: StepInput = {
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
                // The explicit-true capture happens before the header override.
                expect(result.value.processPersonExplicitlyTrue).toBe(true)
                expect(result.value.forceDisablePersonProcessing).toBe(true)
            }
        })

        it('respects $process_person_profile=false when header is false', async () => {
            const input: StepInput = {
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
            const input: StepInput = {
                ...baseInput,
            }

            const result = await normalizeStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.processPerson).toBe(true)
                expect(result.value.processPersonExplicitlyTrue).toBe(false)
                expect(result.value.forceDisablePersonProcessing).toBe(false)
            }
        })

        it('leaves $feature_flag_called events personful when no $process_person_profile property is set', async () => {
            const input: StepInput = {
                ...baseInput,
                event: {
                    ...baseEvent,
                    event: '$feature_flag_called',
                    properties: {
                        $feature_flag: 'new-homepage',
                        $feature_flag_response: 'test',
                        $set: { email: 'user@example.com' },
                    },
                },
            }

            const result = await normalizeStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.processPerson).toBe(true)
                expect(result.value.processPersonExplicitlyTrue).toBe(false)
                expect(result.value.forceDisablePersonProcessing).toBe(false)
                expect(result.value.event.properties?.$process_person_profile).toBeUndefined()
                expect(result.value.event.properties?.$set).toEqual({ email: 'user@example.com' })
            }
        })

        it.each(['$pageview', '$feature_flag_called'])(
            'keeps %s personful when $process_person_profile=true explicitly',
            async (eventName) => {
                const input: StepInput = {
                    ...baseInput,
                    event: {
                        ...baseEvent,
                        event: eventName,
                        properties: { $process_person_profile: true },
                    },
                }

                const result = await normalizeStep(input)

                expect(result.type).toBe(PipelineResultType.OK)
                if (result.type === PipelineResultType.OK) {
                    expect(result.value.processPerson).toBe(true)
                    expect(result.value.processPersonExplicitlyTrue).toBe(true)
                    expect(result.value.forceDisablePersonProcessing).toBe(false)
                }
            }
        )
    })
})
