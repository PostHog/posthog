import { EventSchemaEnforcement, IncomingEventWithTeam, Team } from '../../types'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import { PipelineResultType, drop, ok } from '../pipelines/results'
import { createValidateEventSchemaStep, validateEventAgainstSchema } from './validate-event-schema'

/** Creates a mock EventSchemaEnforcementManager that returns the provided schemas for any team */
function createMockSchemaManager(schemas: EventSchemaEnforcement[]): EventSchemaEnforcementManager {
    // Convert array to Map keyed by event_name for O(1) lookups
    const schemaMap = new Map(schemas.map((s) => [s.event_name, s]))
    return {
        getSchemas: jest.fn().mockResolvedValue(schemaMap),
        getSchemasForTeams: jest.fn().mockResolvedValue({}),
    } as unknown as EventSchemaEnforcementManager
}

describe('validateEventAgainstSchema', () => {
    // Note: The schema only includes required_properties since optional properties
    // are filtered out at the database query level for performance.

    describe('missing required fields', () => {
        it.each([
            ['undefined', undefined],
            ['null', null],
        ])('should reject when required property is %s', (_, value) => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['required_prop', ['String']]]),
            }

            const result = validateEventAgainstSchema({ required_prop: value }, schema)

            expect(result.valid).toBe(false)
            expect(result.errors).toHaveLength(1)
            expect(result.errors[0]).toEqual({
                propertyName: 'required_prop',
                reason: 'missing_required',
            })
        })

        it('should reject when required property is missing from properties object', () => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['required_prop', ['String']]]),
            }

            const result = validateEventAgainstSchema({}, schema)

            expect(result.valid).toBe(false)
            expect(result.errors[0].reason).toBe('missing_required')
        })

        it('should reject when properties object is undefined', () => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['required_prop', ['String']]]),
            }

            const result = validateEventAgainstSchema(undefined, schema)

            expect(result.valid).toBe(false)
            expect(result.errors[0].reason).toBe('missing_required')
        })

        it('should report multiple missing required fields', () => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([
                    ['field1', ['String']],
                    ['field2', ['Numeric']],
                    ['field3', ['Boolean']],
                ]),
            }

            const result = validateEventAgainstSchema({}, schema)

            expect(result.valid).toBe(false)
            expect(result.errors).toHaveLength(3)
        })
    })

    describe('String type coercion', () => {
        it.each([
            ['string', 'hello'],
            ['number', 42],
            ['boolean', true],
            ['object', { foo: 'bar' }],
            ['array', [1, 2, 3]],
        ])('should accept %s as String', (_, value) => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['String']]]),
            }

            const result = validateEventAgainstSchema({ prop: value }, schema)

            expect(result.valid).toBe(true)
        })
    })

    describe('Numeric type coercion', () => {
        it.each([
            ['integer', 42],
            ['float', 3.14],
            ['negative number', -10],
            ['zero', 0],
            ['numeric string', '42'],
            ['negative numeric string', '-10'],
            ['float string', '3.14'],
        ])('should accept %s as Numeric', (_, value) => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['Numeric']]]),
            }

            const result = validateEventAgainstSchema({ prop: value }, schema)

            expect(result.valid).toBe(true)
        })

        it.each([
            ['non-numeric string', 'hello'],
            ['empty string', ''],
            ['whitespace string', '   '],
            ['object', { foo: 'bar' }],
            ['array', [1, 2, 3]],
            ['boolean true', true],
            ['boolean false', false],
            ['Infinity', Infinity],
            ['-Infinity', -Infinity],
            ['NaN', NaN],
            ['string "Infinity"', 'Infinity'],
            ['string "-Infinity"', '-Infinity'],
            ['string "NaN"', 'NaN'],
        ])('should reject %s as Numeric', (_, value) => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['Numeric']]]),
            }

            const result = validateEventAgainstSchema({ prop: value }, schema)

            expect(result.valid).toBe(false)
            expect(result.errors[0].reason).toBe('type_mismatch')
        })
    })

    describe('Boolean type coercion', () => {
        it.each([
            ['true', true],
            ['false', false],
            ['string "true"', 'true'],
            ['string "false"', 'false'],
        ])('should accept %s as Boolean', (_, value) => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['Boolean']]]),
            }

            const result = validateEventAgainstSchema({ prop: value }, schema)

            expect(result.valid).toBe(true)
        })

        it.each([
            ['number 1', 1],
            ['number 0', 0],
            ['string "yes"', 'yes'],
            ['string "no"', 'no'],
            ['string "TRUE"', 'TRUE'],
            ['string "FALSE"', 'FALSE'],
            ['string "True"', 'True'],
            ['string "False"', 'False'],
            ['object', {}],
            ['array', []],
        ])('should reject %s as Boolean', (_, value) => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['Boolean']]]),
            }

            const result = validateEventAgainstSchema({ prop: value }, schema)

            expect(result.valid).toBe(false)
            expect(result.errors[0].reason).toBe('type_mismatch')
        })
    })

    describe('DateTime type coercion', () => {
        it.each([
            ['unix timestamp', 1609459200],
            ['ISO string', '2021-01-01T00:00:00Z'],
            ['ISO string with offset', '2021-01-01T00:00:00+00:00'],
            ['date string', '2021-01-01'],
        ])('should accept %s as DateTime', (_, value) => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['DateTime']]]),
            }

            const result = validateEventAgainstSchema({ prop: value }, schema)

            expect(result.valid).toBe(true)
        })

        it.each([
            ['invalid date string', 'not-a-date'],
            ['object', {}],
            ['array', []],
            ['boolean', true],
        ])('should reject %s as DateTime', (_, value) => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['DateTime']]]),
            }

            const result = validateEventAgainstSchema({ prop: value }, schema)

            expect(result.valid).toBe(false)
            expect(result.errors[0].reason).toBe('type_mismatch')
        })
    })

    describe('Object type coercion', () => {
        it.each([
            ['plain object', { foo: 'bar' }],
            ['empty object', {}],
            ['array', [1, 2, 3]],
            ['empty array', []],
        ])('should accept %s as Object', (_, value) => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['Object']]]),
            }

            const result = validateEventAgainstSchema({ prop: value }, schema)

            expect(result.valid).toBe(true)
        })

        it.each([
            ['string', 'hello'],
            ['number', 42],
            ['boolean', true],
        ])('should reject %s as Object', (_, value) => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['Object']]]),
            }

            const result = validateEventAgainstSchema({ prop: value }, schema)

            expect(result.valid).toBe(false)
            expect(result.errors[0].reason).toBe('type_mismatch')
        })
    })

    describe('multiple required properties', () => {
        it('should accept when all required properties pass validation', () => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([
                    ['name', ['String']],
                    ['age', ['Numeric']],
                ]),
            }

            const result = validateEventAgainstSchema({ name: 'alice', age: 30 }, schema)

            expect(result.valid).toBe(true)
        })

        it('should reject when one of multiple required properties fails', () => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([
                    ['name', ['String']],
                    ['age', ['Numeric']],
                ]),
            }

            const result = validateEventAgainstSchema({ name: 'alice', age: 'not-a-number' }, schema)

            expect(result.valid).toBe(false)
            expect(result.errors).toHaveLength(1)
            expect(result.errors[0].propertyName).toBe('age')
        })
    })

    describe('multi-type properties', () => {
        it('should accept value matching any of the listed types', () => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['String', 'Numeric']]]),
            }

            expect(validateEventAgainstSchema({ prop: 'hello' }, schema).valid).toBe(true)
            expect(validateEventAgainstSchema({ prop: 42 }, schema).valid).toBe(true)
        })

        it('should reject value matching none of the listed types', () => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['Numeric', 'Boolean']]]),
            }

            const result = validateEventAgainstSchema({ prop: { nested: true } }, schema)

            expect(result.valid).toBe(false)
            expect(result.errors[0].expectedTypes).toEqual(['Numeric', 'Boolean'])
        })
    })

    describe('unknown types', () => {
        it('should allow values for unknown property types', () => {
            const schema: EventSchemaEnforcement = {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['UnknownType']]]),
            }

            const result = validateEventAgainstSchema({ prop: 'anything' }, schema)

            expect(result.valid).toBe(true)
        })
    })
})

describe('createValidateEventSchemaStep', () => {
    const createInput = (eventName: string, properties: Record<string, unknown> | undefined) => ({
        eventWithTeam: {
            event: {
                event: eventName,
                distinct_id: 'user123',
                team_id: 1,
                uuid: '123e4567-e89b-12d3-a456-426614174000',
                ip: '127.0.0.1',
                site_url: 'https://example.com',
                now: '2021-01-01T00:00:00Z',
                properties,
            },
            team: {
                id: 1,
                name: 'Test Team',
            } as unknown as Team,
            message: {} as any,
            headers: {} as any,
        } as unknown as IncomingEventWithTeam,
    })

    it('should pass events when team has no enforced schemas', async () => {
        const mockManager = createMockSchemaManager([])
        const step = createValidateEventSchemaStep(mockManager)
        const input = createInput('test_event', { prop: 'value' })

        const result = await step(input)

        expect(result).toEqual(ok(input))
    })

    it('should pass events that have no matching schema', async () => {
        const schemas: EventSchemaEnforcement[] = [
            {
                event_name: 'other_event',
                required_properties: new Map([['required_prop', ['String']]]),
            },
        ]
        const mockManager = createMockSchemaManager(schemas)
        const step = createValidateEventSchemaStep(mockManager)
        const input = createInput('test_event', {})

        const result = await step(input)

        expect(result).toEqual(ok(input))
    })

    it('should pass events that match schema requirements', async () => {
        const schemas: EventSchemaEnforcement[] = [
            {
                event_name: 'test_event',
                required_properties: new Map([['required_prop', ['String']]]),
            },
        ]
        const mockManager = createMockSchemaManager(schemas)
        const step = createValidateEventSchemaStep(mockManager)
        const input = createInput('test_event', { required_prop: 'hello' })

        const result = await step(input)

        expect(result).toEqual(ok(input))
    })

    it('should drop events missing required properties', async () => {
        const schemas: EventSchemaEnforcement[] = [
            {
                event_name: 'test_event',
                required_properties: new Map([['required_prop', ['String']]]),
            },
        ]
        const mockManager = createMockSchemaManager(schemas)
        const step = createValidateEventSchemaStep(mockManager)
        const input = createInput('test_event', {})

        const result = await step(input)

        expect(result).toEqual(
            drop(
                'schema_validation_failed',
                [],
                [
                    {
                        type: 'schema_validation_failed',
                        details: {
                            eventUuid: '123e4567-e89b-12d3-a456-426614174000',
                            eventName: 'test_event',
                            distinctId: 'user123',
                            errors: [
                                {
                                    property: 'required_prop',
                                    reason: 'missing_required',
                                    expectedTypes: undefined,
                                    actualValue: undefined,
                                },
                            ],
                        },
                    },
                ]
            )
        )
    })

    it('should drop events with type mismatch on required properties', async () => {
        const schemas: EventSchemaEnforcement[] = [
            {
                event_name: 'test_event',
                required_properties: new Map([['numeric_prop', ['Numeric']]]),
            },
        ]
        const mockManager = createMockSchemaManager(schemas)
        const step = createValidateEventSchemaStep(mockManager)
        const input = createInput('test_event', { numeric_prop: 'not-a-number' })

        const result = await step(input)

        expect(result).toEqual(
            drop(
                'schema_validation_failed',
                [],
                [
                    {
                        type: 'schema_validation_failed',
                        details: {
                            eventUuid: '123e4567-e89b-12d3-a456-426614174000',
                            eventName: 'test_event',
                            distinctId: 'user123',
                            errors: [
                                {
                                    property: 'numeric_prop',
                                    reason: 'type_mismatch',
                                    expectedTypes: ['Numeric'],
                                    actualValue: 'not-a-number',
                                },
                            ],
                        },
                    },
                ]
            )
        )
    })

    it('should include multiple errors in warning details', async () => {
        const schemas: EventSchemaEnforcement[] = [
            {
                event_name: 'test_event',
                required_properties: new Map([
                    ['field1', ['String']],
                    ['field2', ['Numeric']],
                ]),
            },
        ]
        const mockManager = createMockSchemaManager(schemas)
        const step = createValidateEventSchemaStep(mockManager)
        const input = createInput('test_event', { field2: 'not-numeric' })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DROP)
        if (result.type === PipelineResultType.DROP) {
            expect(result.warnings[0].details.errors).toHaveLength(2)
        }
    })

    it('should stringify object values in error details', async () => {
        const schemas: EventSchemaEnforcement[] = [
            {
                event_name: 'test_event',
                required_properties: new Map([['prop', ['Boolean']]]),
            },
        ]
        const mockManager = createMockSchemaManager(schemas)
        const step = createValidateEventSchemaStep(mockManager)
        const input = createInput('test_event', { prop: { nested: 'object' } })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DROP)
        if (result.type === PipelineResultType.DROP) {
            expect(result.warnings[0].details.errors[0].actualValue).toBe('{"nested":"object"}')
        }
    })
})
