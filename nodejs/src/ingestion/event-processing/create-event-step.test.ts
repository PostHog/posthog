import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { createTestMessage } from '../../../tests/helpers/kafka-message'
import { MaterializedColumnSlot, Person, PersonMode, PreIngestionEvent, ProjectId, TimestampFormat } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { MaterializedColumnSlotManager } from '../../utils/materialized-column-slot-manager'
import { castTimestampOrNow } from '../../utils/utils'
import { isOkResult } from '../pipelines/results'
import { CreateEventStepConfig, CreateEventStepInput, createCreateEventStep } from './create-event-step'

// Mock MaterializedColumnSlotManager
const createMockSlotManager = (slots: MaterializedColumnSlot[] = []): MaterializedColumnSlotManager => {
    return {
        getSlots: jest.fn().mockResolvedValue(slots),
        getSlotsForTeams: jest.fn().mockResolvedValue({}),
    } as unknown as MaterializedColumnSlotManager
}

describe('create-event-step', () => {
    let mockPerson: Person
    let mockPreparedEvent: PreIngestionEvent
    let mockMessage: Message
    let mockConfig: CreateEventStepConfig

    beforeEach(() => {
        mockMessage = createTestMessage()
        mockConfig = { materializedColumnSlotManager: createMockSlotManager() }
        mockPerson = {
            team_id: 1,
            properties: { email: 'test@example.com', name: 'Test User' },
            uuid: 'person-uuid-123',
            created_at: DateTime.fromISO('2023-01-01T00:00:00.000Z'),
            force_upgrade: false,
        }

        mockPreparedEvent = {
            eventUuid: 'event-uuid-456',
            event: '$pageview',
            teamId: 1,
            projectId: 1 as ProjectId,
            distinctId: 'distinct-id-789',
            properties: { $current_url: 'https://example.com' },
            timestamp: castTimestampOrNow('2023-01-01T00:00:00.000Z', TimestampFormat.ISO),
        }
    })

    describe('createCreateEventStep', () => {
        it('should create event with processPerson=true', async () => {
            const step = createCreateEventStep(mockConfig)
            const input = {
                person: mockPerson,
                preparedEvent: mockPreparedEvent,
                processPerson: true,
                historicalMigration: false,
                inputHeaders: createTestEventHeaders(),
                inputMessage: mockMessage,
                lastStep: 'prepareEventStep',
            }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                const value = result.value
                expect(value.eventToEmit).toBeDefined()
                if (!value.eventToEmit) {
                    return
                }
                expect(value.eventToEmit.uuid).toBe('event-uuid-456')
                expect(value.eventToEmit.event).toBe('$pageview')
                expect(value.eventToEmit.team_id).toBe(1)
                expect(value.eventToEmit.distinct_id).toBe('distinct-id-789')
                expect(value.eventToEmit.person_id).toBe('person-uuid-123')
                expect(value.eventToEmit.person_mode).toBe('full')
                expect(parseJSON(value.eventToEmit.person_properties || '{}')).toEqual({
                    email: 'test@example.com',
                    name: 'Test User',
                })
            }
            expect(result.sideEffects).toHaveLength(0)
        })

        it('should create event with processPerson=false', async () => {
            const step = createCreateEventStep(mockConfig)
            const input = {
                person: mockPerson,
                preparedEvent: mockPreparedEvent,
                processPerson: false,
                historicalMigration: false,
                inputHeaders: createTestEventHeaders(),
                inputMessage: mockMessage,
                lastStep: 'prepareEventStep',
            }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                const value = result.value
                expect(value.eventToEmit).toBeDefined()
                if (!value.eventToEmit) {
                    return
                }
                expect(value.eventToEmit.person_mode).toBe('propertyless')
                expect(value.eventToEmit.person_properties).toBe('{}')
            }
            expect(result.sideEffects).toHaveLength(0)
        })

        it('should handle person with force_upgrade=true', async () => {
            const personWithForceUpgrade: Person = {
                ...mockPerson,
                force_upgrade: true,
            }

            const step = createCreateEventStep(mockConfig)
            const input = {
                person: personWithForceUpgrade,
                preparedEvent: mockPreparedEvent,
                processPerson: true,
                historicalMigration: false,
                inputHeaders: createTestEventHeaders(),
                inputMessage: mockMessage,
                lastStep: 'prepareEventStep',
            }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                const value = result.value
                expect(value.eventToEmit).toBeDefined()
                if (!value.eventToEmit) {
                    return
                }
                expect(value.eventToEmit.person_mode).toBe('force_upgrade')
            }
        })

        it('should include $set properties in person_properties when processPerson=true', async () => {
            const eventWithSetProperties: PreIngestionEvent = {
                ...mockPreparedEvent,
                properties: {
                    ...mockPreparedEvent.properties,
                    $set: { new_property: 'new_value' },
                },
            }

            const step = createCreateEventStep(mockConfig)
            const input = {
                person: mockPerson,
                preparedEvent: eventWithSetProperties,
                processPerson: true,
                historicalMigration: false,
                inputHeaders: createTestEventHeaders(),
                inputMessage: mockMessage,
                lastStep: 'prepareEventStep',
            }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                const value = result.value
                expect(value.eventToEmit).toBeDefined()
                if (!value.eventToEmit) {
                    return
                }
                const personProperties = parseJSON(value.eventToEmit.person_properties || '{}')
                expect(personProperties).toEqual({
                    email: 'test@example.com',
                    name: 'Test User',
                    new_property: 'new_value',
                })
            }
        })

        it('should preserve event properties as JSON string', async () => {
            const step = createCreateEventStep(mockConfig)
            const input = {
                person: mockPerson,
                preparedEvent: mockPreparedEvent,
                processPerson: true,
                historicalMigration: false,
                inputHeaders: createTestEventHeaders(),
                inputMessage: mockMessage,
                lastStep: 'prepareEventStep',
            }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                const value = result.value
                expect(value.eventToEmit).toBeDefined()
                if (!value.eventToEmit) {
                    return
                }
                expect(typeof value.eventToEmit.properties).toBe('string')
                expect(parseJSON(value.eventToEmit.properties || '{}')).toEqual({
                    $current_url: 'https://example.com',
                })
            }
        })

        it('should handle events with elements_chain', async () => {
            const eventWithElements: PreIngestionEvent = {
                ...mockPreparedEvent,
                properties: {
                    ...mockPreparedEvent.properties,
                    $elements_chain: 'button:0;div:1;body:2',
                },
            }

            const step = createCreateEventStep(mockConfig)
            const input = {
                person: mockPerson,
                preparedEvent: eventWithElements,
                processPerson: true,
                historicalMigration: false,
                inputHeaders: createTestEventHeaders(),
                inputMessage: mockMessage,
                lastStep: 'prepareEventStep',
            }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                const value = result.value
                expect(value.eventToEmit).toBeDefined()
                if (!value.eventToEmit) {
                    return
                }
                expect(value.eventToEmit.elements_chain).toBe('button:0;div:1;body:2')
            }
        })

        it('should work with generic input types that have required properties', async () => {
            interface CustomInput extends CreateEventStepInput {
                customProperty: string
                lastStep: string
            }

            const step = createCreateEventStep<CustomInput>(mockConfig)
            const input: CustomInput = {
                person: mockPerson,
                preparedEvent: mockPreparedEvent,
                processPerson: true,
                historicalMigration: false,
                inputHeaders: createTestEventHeaders(),
                inputMessage: mockMessage,
                customProperty: 'test',
                lastStep: 'prepareEventStep',
            }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value.eventToEmit).toBeDefined()
            }
        })

        it('should set correct timestamps', async () => {
            const step = createCreateEventStep(mockConfig)
            const input = {
                person: mockPerson,
                preparedEvent: mockPreparedEvent,
                processPerson: true,
                historicalMigration: false,
                inputHeaders: createTestEventHeaders(),
                inputMessage: mockMessage,
                lastStep: 'prepareEventStep',
            }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                const value = result.value
                expect(value.eventToEmit).toBeDefined()
                if (!value.eventToEmit) {
                    return
                }
                expect(value.eventToEmit.timestamp).toBeTruthy()
                expect(value.eventToEmit.created_at).toBeTruthy()
                expect(value.eventToEmit.person_created_at).toBeTruthy()
            }
        })

        it('should handle different event types', async () => {
            const events = ['$pageview', '$identify', '$set', 'custom_event']

            for (const eventName of events) {
                const eventWithType: PreIngestionEvent = {
                    ...mockPreparedEvent,
                    event: eventName,
                }

                const step = createCreateEventStep(mockConfig)
                const input = {
                    person: mockPerson,
                    preparedEvent: eventWithType,
                    processPerson: true,
                    historicalMigration: false,
                    inputHeaders: createTestEventHeaders(),
                    inputMessage: mockMessage,
                    lastStep: 'prepareEventStep',
                }

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                if (isOkResult(result)) {
                    expect(result.value.eventToEmit).toBeDefined()
                    if (!result.value.eventToEmit) {
                        return
                    }
                    expect(result.value.eventToEmit.event).toBe(eventName)
                }
            }
        })

        describe('historicalMigration flag', () => {
            it('should include historical_migration in event when historicalMigration=true', async () => {
                const step = createCreateEventStep(mockConfig)
                const input = {
                    person: mockPerson,
                    preparedEvent: mockPreparedEvent,
                    processPerson: true,
                    historicalMigration: true,
                    inputHeaders: createTestEventHeaders(),
                    inputMessage: mockMessage,
                    lastStep: 'prepareEventStep',
                }

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                if (isOkResult(result)) {
                    expect(result.value.eventToEmit).toBeDefined()
                    if (!result.value.eventToEmit) {
                        return
                    }
                    expect(result.value.eventToEmit.historical_migration).toBe(true)
                }
            })

            it('should not include historical_migration in event when historicalMigration=false', async () => {
                const step = createCreateEventStep(mockConfig)
                const input = {
                    person: mockPerson,
                    preparedEvent: mockPreparedEvent,
                    processPerson: true,
                    historicalMigration: false,
                    inputHeaders: createTestEventHeaders(),
                    inputMessage: mockMessage,
                    lastStep: 'prepareEventStep',
                }

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                if (isOkResult(result)) {
                    expect(result.value.eventToEmit).toBeDefined()
                    if (!result.value.eventToEmit) {
                        return
                    }
                    expect(result.value.eventToEmit.historical_migration).toBeUndefined()
                }
            })
        })

        describe('EAV property extraction', () => {
            it.each([
                ['String', 'plan', 'enterprise', { value_string: 'enterprise' }],
                ['Numeric', 'revenue', 123.45, { value_numeric: 123.45 }],
                ['Numeric', 'count', '42', { value_numeric: 42 }],
                ['Boolean', 'is_active', true, { value_bool: 1 }],
                ['Boolean', 'is_active', 'true', { value_bool: 1 }],
                ['Boolean', 'is_active', '1', { value_bool: 1 }],
                ['Boolean', 'is_active', false, { value_bool: 0 }],
                ['Boolean', 'is_active', 'false', { value_bool: 0 }],
                ['Boolean', 'is_active', '0', { value_bool: 0 }],
                [
                    'DateTime',
                    'created_at',
                    '2026-01-09T07:10:36.367000Z',
                    { value_datetime: '2026-01-09 07:10:36.367' },
                ],
                ['DateTime', 'created_at', '2026-01-09T07:10:36Z', { value_datetime: '2026-01-09 07:10:36.000' }],
            ])(
                'should extract %s property %s with value %p',
                async (propertyType, propertyName, propertyValue, expectedValues) => {
                    const slot: MaterializedColumnSlot = {
                        property_name: propertyName,
                        slot_index: 0,
                        property_type: propertyType as 'String' | 'Numeric' | 'Boolean' | 'DateTime',
                        state: 'READY',
                        materialization_type: 'eav',
                    }

                    const config = { materializedColumnSlotManager: createMockSlotManager([slot]) }
                    const step = createCreateEventStep(config)

                    const eventWithProperty: PreIngestionEvent = {
                        ...mockPreparedEvent,
                        properties: { [propertyName]: propertyValue },
                    }

                    const input = {
                        person: mockPerson,
                        preparedEvent: eventWithProperty,
                        processPerson: true,
                        historicalMigration: false,
                        inputHeaders: createTestEventHeaders(),
                        inputMessage: mockMessage,
                        lastStep: 'prepareEventStep',
                    }

                    const result = await step(input)

                    expect(isOkResult(result)).toBe(true)
                    if (isOkResult(result)) {
                        expect(result.value.eavPropertiesToEmit).toHaveLength(1)
                        const eavProp = result.value.eavPropertiesToEmit![0]
                        expect(eavProp.key).toBe(propertyName)
                        for (const [key, value] of Object.entries(expectedValues)) {
                            expect(eavProp[key as keyof typeof eavProp]).toBe(value)
                        }
                    }
                }
            )

            it.each([
                ['Numeric', 'revenue', 'not-a-number'],
                ['Numeric', 'revenue', {}],
                ['Boolean', 'is_active', 'maybe'],
                ['Boolean', 'is_active', 2],
                ['DateTime', 'created_at', 'not-a-date'],
                ['DateTime', 'created_at', 123],
                ['DateTime', 'created_at', {}],
            ])(
                'should not extract %s property %s with invalid value %p',
                async (propertyType, propertyName, propertyValue) => {
                    const slot: MaterializedColumnSlot = {
                        property_name: propertyName,
                        slot_index: 0,
                        property_type: propertyType as 'String' | 'Numeric' | 'Boolean' | 'DateTime',
                        state: 'READY',
                        materialization_type: 'eav',
                    }

                    const config = { materializedColumnSlotManager: createMockSlotManager([slot]) }
                    const step = createCreateEventStep(config)

                    const eventWithProperty: PreIngestionEvent = {
                        ...mockPreparedEvent,
                        properties: { [propertyName]: propertyValue },
                    }

                    const input = {
                        person: mockPerson,
                        preparedEvent: eventWithProperty,
                        processPerson: true,
                        historicalMigration: false,
                        inputHeaders: createTestEventHeaders(),
                        inputMessage: mockMessage,
                        lastStep: 'prepareEventStep',
                    }

                    const result = await step(input)

                    expect(isOkResult(result)).toBe(true)
                    if (isOkResult(result)) {
                        // Should either have no EAV properties or have one with null values
                        const eavProps = result.value.eavPropertiesToEmit || []
                        if (eavProps.length > 0) {
                            const eavProp = eavProps[0]
                            expect(eavProp.value_string).toBeNull()
                            expect(eavProp.value_numeric).toBeNull()
                            expect(eavProp.value_bool).toBeNull()
                            expect(eavProp.value_datetime).toBeNull()
                        }
                    }
                }
            )

            it('should skip DMAT slots', async () => {
                const slot: MaterializedColumnSlot = {
                    property_name: 'browser',
                    slot_index: 0,
                    property_type: 'String',
                    state: 'READY',
                    materialization_type: 'dmat',
                }

                const config = { materializedColumnSlotManager: createMockSlotManager([slot]) }
                const step = createCreateEventStep(config)

                const eventWithProperty: PreIngestionEvent = {
                    ...mockPreparedEvent,
                    properties: { browser: 'Chrome' },
                }

                const input = {
                    person: mockPerson,
                    preparedEvent: eventWithProperty,
                    processPerson: true,
                    historicalMigration: false,
                    inputHeaders: createTestEventHeaders(),
                    inputMessage: mockMessage,
                    lastStep: 'prepareEventStep',
                }

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                if (isOkResult(result)) {
                    expect(result.value.eavPropertiesToEmit).toHaveLength(0)
                }
            })

            it('should skip slots not in READY or BACKFILL state', async () => {
                const slot: MaterializedColumnSlot = {
                    property_name: 'plan',
                    slot_index: 0,
                    property_type: 'String',
                    state: 'ERROR',
                    materialization_type: 'eav',
                }

                const config = { materializedColumnSlotManager: createMockSlotManager([slot]) }
                const step = createCreateEventStep(config)

                const eventWithProperty: PreIngestionEvent = {
                    ...mockPreparedEvent,
                    properties: { plan: 'enterprise' },
                }

                const input = {
                    person: mockPerson,
                    preparedEvent: eventWithProperty,
                    processPerson: true,
                    historicalMigration: false,
                    inputHeaders: createTestEventHeaders(),
                    inputMessage: mockMessage,
                    lastStep: 'prepareEventStep',
                }

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                if (isOkResult(result)) {
                    expect(result.value.eavPropertiesToEmit).toHaveLength(0)
                }
            })
        })

        describe('person modes', () => {
            it.each([
                ['full', { processPerson: true, force_upgrade: false }, 'full' as PersonMode],
                ['propertyless', { processPerson: false, force_upgrade: false }, 'propertyless' as PersonMode],
                ['force_upgrade', { processPerson: true, force_upgrade: true }, 'force_upgrade' as PersonMode],
            ])('should set person_mode=%s when processPerson=%p and force_upgrade=%p', async (_, config, expected) => {
                const person: Person = {
                    ...mockPerson,
                    force_upgrade: config.force_upgrade,
                }

                const step = createCreateEventStep(mockConfig)
                const input = {
                    person,
                    preparedEvent: mockPreparedEvent,
                    processPerson: config.processPerson,
                    historicalMigration: false,
                    inputHeaders: createTestEventHeaders(),
                    inputMessage: mockMessage,
                    lastStep: 'prepareEventStep',
                }

                const result = await step(input)

                expect(isOkResult(result)).toBe(true)
                if (isOkResult(result)) {
                    expect(result.value.eventToEmit).toBeDefined()
                    if (!result.value.eventToEmit) {
                        return
                    }
                    expect(result.value.eventToEmit.person_mode).toBe(expected)
                }
            })
        })
    })
})
