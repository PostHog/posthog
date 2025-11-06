import { Message } from 'node-rdkafka'
import { v4 } from 'uuid'

import { JwtVerificationStatus, PipelineEvent, ProjectId, Team } from '../../types'
import { PerDistinctIdPipelineInput } from '../ingestion-consumer'
import { PipelineResultType } from '../pipelines/results'
import { createNormalizeProcessPersonFlagStep } from './normalize-process-person-flag-step'

const createTestTeam = (overrides: Partial<Team> = {}): Team => ({
    id: 1,
    project_id: 1 as ProjectId,
    organization_id: 'test-org-id',
    uuid: v4(),
    name: 'Test Team',
    anonymize_ips: false,
    api_token: 'test-api-token',
    slack_incoming_webhook: null,
    session_recording_opt_in: true,
    person_processing_opt_out: null,
    heatmaps_opt_in: null,
    ingested_event: true,
    person_display_name_properties: null,
    test_account_filters: null,
    cookieless_server_hash_mode: null,
    timezone: 'UTC',
    available_features: [],
    drop_events_older_than_seconds: null,
    ...overrides,
})

describe('normalizeProcessPersonFlagStep', () => {
    const team = createTestTeam()

    const baseEvent: PipelineEvent = {
        distinct_id: 'my_id',
        ip: null,
        site_url: '',
        team_id: 1,
        now: new Date().toISOString(),
        event: '$pageview',
        properties: {},
        uuid: v4(),
    }

    const baseInput: PerDistinctIdPipelineInput = {
        message: {} as Message,
        event: baseEvent,
        team,
        headers: { force_disable_person_processing: false },
        personsStoreForBatch: {} as any,
        groupStoreForBatch: {} as any,
        verified: JwtVerificationStatus.NotVerified,
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
                headers: { force_disable_person_processing: true },
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
                headers: { force_disable_person_processing: false },
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
                headers: { force_disable_person_processing: true },
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
                headers: { force_disable_person_processing: false },
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
