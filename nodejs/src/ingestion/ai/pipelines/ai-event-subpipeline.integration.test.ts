import { DateTime } from 'luxon'

import { PluginEvent } from '~/plugin-scaffold'

import { createTestEventHeaders } from '../../../../tests/helpers/event-headers'
import { createTestMessage } from '../../../../tests/helpers/kafka-message'
import { createTestPluginEvent } from '../../../../tests/helpers/plugin-event'
import { createTestTeam } from '../../../../tests/helpers/team'
import { InternalPerson, PropertyUpdateOperation } from '../../../types'
import { parseJSON } from '../../../utils/json-parse'
import { AI_EVENTS_OUTPUT, EVENTS_OUTPUT, IngestionOutputs } from '../../event-processing/ingestion-outputs'
import { newPipelineBuilder } from '../../pipelines/builders'
import { createContext } from '../../pipelines/helpers'
import { PipelineResultType, ok } from '../../pipelines/results'
import { AiEventSubpipelineConfig, AiEventSubpipelineInput, createAiEventSubpipeline } from './ai-event-subpipeline'

const team = createTestTeam()
const message = createTestMessage()
const headers = createTestEventHeaders()

const existingPerson: InternalPerson = {
    id: '1',
    team_id: team.id,
    uuid: 'person-uuid-1',
    properties: { email: 'test@example.com' },
    is_user_id: null,
    is_identified: false,
    properties_last_updated_at: {},
    properties_last_operation: { email: PropertyUpdateOperation.Set },
    created_at: DateTime.fromISO('2020-01-01T00:00:00Z'),
    version: 0,
    last_seen_at: null,
}

function createAiEvent(overrides: Partial<PluginEvent> = {}): PluginEvent {
    return createTestPluginEvent({
        event: '$ai_generation',
        team_id: team.id,
        timestamp: '2020-02-23T02:15:00Z',
        properties: {
            $ai_model: 'gpt-4',
            $ai_provider: 'openai',
            $ai_input_tokens: 100,
            $ai_output_tokens: 50,
            ...overrides.properties,
        },
        ...overrides,
        // Restore properties after spread since overrides may have properties
        ...(overrides.properties
            ? {
                  properties: {
                      $ai_model: 'gpt-4',
                      $ai_provider: 'openai',
                      $ai_input_tokens: 100,
                      $ai_output_tokens: 50,
                      ...overrides.properties,
                  },
              }
            : {}),
    })
}

function buildPipeline(configOverrides: Partial<AiEventSubpipelineConfig> = {}) {
    const mockProduce = jest.fn().mockResolvedValue(undefined)

    const config: AiEventSubpipelineConfig = {
        options: {
            SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: true,
            PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: 0,
            PERSON_MERGE_ASYNC_ENABLED: false,
            PERSON_MERGE_ASYNC_TOPIC: '',
            PERSON_MERGE_SYNC_BATCH_SIZE: 0,
            PERSON_JSONB_SIZE_ESTIMATE_ENABLE: 0,
            PERSON_PROPERTIES_UPDATE_ALL: false,
        },
        outputs: new IngestionOutputs({
            [EVENTS_OUTPUT]: {
                topic: 'events_topic',
                producer: { produce: mockProduce } as any,
            },
            [AI_EVENTS_OUTPUT]: {
                topic: 'ai_events_topic',
                producer: { produce: mockProduce } as any,
            },
        }),
        teamManager: {
            setTeamIngestedEvent: jest.fn().mockResolvedValue(undefined),
        } as any,
        groupTypeManager: {
            fetchGroupTypeIndex: jest.fn().mockResolvedValue(0),
        } as any,
        hogTransformer: {
            transformEventAndProduceMessages: (event: PluginEvent) => Promise.resolve({ event, invocationResults: [] }),
        } as any,
        personsStore: {
            fetchForChecking: jest.fn().mockResolvedValue(null),
            getPersonlessBatchResult: jest.fn().mockReturnValue(false),
            fetchForUpdate: jest.fn().mockResolvedValue(existingPerson),
            updatePersonWithPropertiesDiffForUpdate: jest.fn().mockResolvedValue([existingPerson, [], false]),
        } as any,
        groupStore: {} as any,
        kafkaProducer: {
            queueMessages: jest.fn().mockResolvedValue(undefined),
        } as any,
        splitAiEventsConfig: { enabled: false, enabledTeams: '*', stripHeavyProperties: false },
        groupId: 'test-group',
        topHog: (step) => step,
        ...configOverrides,
    }

    return {
        pipeline: createAiEventSubpipeline(newPipelineBuilder<AiEventSubpipelineInput>(), config).build(),
        mockProduce,
        config,
    }
}

function createInput(event: PluginEvent): AiEventSubpipelineInput {
    return { message, event, team, headers }
}

function getProduceCall(mockProduce: jest.Mock) {
    expect(mockProduce).toHaveBeenCalledTimes(1)
    const call = mockProduce.mock.calls[0][0]
    const event = parseJSON(call.value.toString())
    return {
        topic: call.topic as string,
        key: call.key as string,
        headers: call.headers as Record<string, string>,
        event,
        properties: parseJSON(event.properties) as Record<string, unknown>,
    }
}

describe('AI event subpipeline integration', () => {
    it('exercises all steps: hog transform → normalize → AI enrich → person → prepare → emit', async () => {
        const event = createAiEvent({
            properties: {
                $ai_model: 'gpt-4',
                $ai_provider: 'openai',
                $ai_input_tokens: 1000,
                $ai_output_tokens: 500,
                $ai_trace_id: 12345,
                // $set triggers person property handling
                $set: { plan: 'enterprise' },
                // $groups triggers group property lookup in prepareEvent
                $groups: { company: 'posthog' },
            },
        })

        const { pipeline, mockProduce } = buildPipeline({
            // Hog transform adds a property with un-normalized casing
            hogTransformer: {
                transformEventAndProduceMessages: (e: PluginEvent) =>
                    Promise.resolve({
                        event: { ...e, properties: { ...e.properties, $hog_transformed: true } },
                        invocationResults: [{}],
                    }),
            } as any,
        })

        const result = await pipeline.process(createContext(ok(createInput(event))))
        expect(result.result.type).toBe(PipelineResultType.OK)

        const { topic, event: produced, properties } = getProduceCall(mockProduce)

        // Emit step: correct topic
        expect(topic).toBe('events_topic')

        // Event identity preserved
        expect(produced.event).toBe('$ai_generation')
        expect(produced.team_id).toBe(team.id)
        expect(produced.distinct_id).toBe(event.distinct_id)

        // Hog transform step: property was added
        expect(properties.$hog_transformed).toBe(true)

        // Normalize step: $process_person_profile defaults to true (person_mode=full)
        expect(produced.person_mode).toBe('full')

        // AI enrich step: cost calculated, trace ID normalized to string
        expect(properties.$ai_input_cost_usd).toBeGreaterThan(0)
        expect(properties.$ai_output_cost_usd).toBeGreaterThan(0)
        expect(typeof properties.$ai_total_cost_usd).toBe('number')
        expect(properties.$ai_trace_id).toBe('12345')

        // Person step: person resolved from personsStore
        expect(produced.person_id).toBe(existingPerson.uuid)
        // $set person properties merged onto the event
        expect(parseJSON(produced.person_properties)).toMatchObject({ email: 'test@example.com', plan: 'enterprise' })

        // Prepare step: group resolved via groupTypeManager
        expect(properties.$group_0).toBe('posthog')
    })

    it('personless: $process_person_profile=false produces event with propertyless person_mode', async () => {
        const event = createAiEvent({
            properties: {
                $process_person_profile: false,
            },
        })

        const { pipeline, mockProduce } = buildPipeline()
        const result = await pipeline.process(createContext(ok(createInput(event))))
        expect(result.result.type).toBe(PipelineResultType.OK)

        const { event: produced, properties } = getProduceCall(mockProduce)

        // Personless: person_mode is propertyless, person properties are empty
        expect(produced.person_mode).toBe('propertyless')
        expect(parseJSON(produced.person_properties)).toEqual({})

        // AI enrichment still applied
        expect(properties.$ai_input_cost_usd).toBeDefined()
    })

    it('hog transform dropping event short-circuits the pipeline', async () => {
        const event = createAiEvent()

        const { pipeline, mockProduce } = buildPipeline({
            hogTransformer: {
                transformEventAndProduceMessages: () => Promise.resolve({ event: null, invocationResults: [{}] }),
            } as any,
        })

        const result = await pipeline.process(createContext(ok(createInput(event))))
        expect(result.result.type).toBe(PipelineResultType.DROP)
        expect(mockProduce).not.toHaveBeenCalled()
    })
})
