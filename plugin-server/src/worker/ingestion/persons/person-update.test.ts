import { PluginEvent } from '@posthog/plugin-scaffold'

import { personProfileIgnoredPropertiesCounter, personProfileUpdateOutcomeCounter } from './metrics'
import { eventToPersonProperties } from './person-property-utils'
import { applyEventPropertyUpdates, computeEventPropertyUpdates } from './person-update'

jest.mock('./metrics', () => ({
    personProfileUpdateOutcomeCounter: {
        labels: jest.fn().mockReturnValue({
            inc: jest.fn(),
        }),
    },
    personProfileIgnoredPropertiesCounter: {
        labels: jest.fn().mockReturnValue({
            inc: jest.fn(),
        }),
    },
}))

const mockPersonProfileUpdateOutcomeCounter = personProfileUpdateOutcomeCounter as jest.Mocked<
    typeof personProfileUpdateOutcomeCounter
>
const mockPersonProfileIgnoredPropertiesCounter = personProfileIgnoredPropertiesCounter as jest.Mocked<
    typeof personProfileIgnoredPropertiesCounter
>

describe('person-update', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })
    describe('computeEventPropertyUpdates', () => {
        describe('property changes', () => {
            it('should compute updates when custom properties are updated', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { custom_prop: 'new_value' },
                    },
                } as any

                const personProperties = { custom_prop: 'old_value' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ custom_prop: 'new_value' })
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
                expect(mockPersonProfileUpdateOutcomeCounter.labels({ outcome: 'changed' }).inc).toHaveBeenCalled()
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            })

            it('should compute updates when properties are unset', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $unset: ['prop_to_remove'],
                    },
                } as any

                const personProperties = { prop_to_remove: 'value', other_prop: 'keep' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toUnset).toEqual(['prop_to_remove'])
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })

            it('should compute updates when setting a new property', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { new_prop: 'value' },
                    },
                } as any

                const personProperties = {}

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ new_prop: 'value' })
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })

            it('should compute updates when $set_once sets a property that does not exist', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set_once: { first_seen: '2024-01-01' },
                    },
                } as any

                const personProperties = {}

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ first_seen: '2024-01-01' })
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })

            it('should compute updates when a new eventToPersonProperty is set (not just updated)', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { $browser: 'Chrome' },
                    },
                } as any

                const personProperties = {}

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $browser: 'Chrome' })
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })
        })

        describe('eventToPersonProperties accepted at event level', () => {
            it.each(Array.from(eventToPersonProperties))(
                'should accept "%s" updates at event level (filtering happens at batch level)',
                (propertyName) => {
                    const event: PluginEvent = {
                        event: 'pageview',
                        properties: {
                            $set: { [propertyName]: 'new_value' },
                        },
                    } as any

                    const personProperties = { [propertyName]: 'old_value' }

                    const result = computeEventPropertyUpdates(event, personProperties)

                    expect(result.hasChanges).toBe(true)
                    expect(result.toSet).toEqual({ [propertyName]: 'new_value' })
                    // At event level, this property would be marked as ignored (outcome: 'ignored')
                    // but it's still included in toSet for batch-level filtering
                    expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'ignored' })
                    expect(mockPersonProfileUpdateOutcomeCounter.labels({ outcome: 'ignored' }).inc).toHaveBeenCalled()
                    expect(mockPersonProfileIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                        property: propertyName,
                    })
                    expect(
                        mockPersonProfileIgnoredPropertiesCounter.labels({ property: propertyName }).inc
                    ).toHaveBeenCalled()
                }
            )

            it('should accept $geoip_* property updates at event level (filtering happens at batch level)', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { $geoip_city_name: 'San Francisco' },
                    },
                } as any

                const personProperties = { $geoip_city_name: 'New York' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $geoip_city_name: 'San Francisco' })
                // At event level, geoip properties would be marked as ignored
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'ignored' })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                    property: '$geoip_city_name',
                })
            })

            it('should accept eventToPersonProperties even when mixed with unchanged custom properties', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { $browser: 'Chrome', custom_prop: 'same_value' },
                    },
                } as any

                const personProperties = { $browser: 'Firefox', custom_prop: 'same_value' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $browser: 'Chrome' })
                // At event level, $browser would be marked as ignored
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'ignored' })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                    property: '$browser',
                })
            })

            it('should accept multiple eventToPersonProperties at event level', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: {
                            $browser: 'Chrome',
                            utm_source: 'google',
                            utm_campaign: 'spring_sale',
                            $os: 'macOS',
                        },
                    },
                } as any

                const personProperties = {
                    $browser: 'Firefox',
                    utm_source: 'twitter',
                    utm_campaign: 'winter_sale',
                    $os: 'Windows',
                }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                // At event level, all these properties would be marked as ignored
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'ignored' })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({ property: '$browser' })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                    property: 'utm_source',
                })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({
                    property: 'utm_campaign',
                })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).toHaveBeenCalledWith({ property: '$os' })
            })
        })

        describe('no changes', () => {
            it('should return no changes when no properties are provided', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {},
                } as any

                const personProperties = { existing_prop: 'value' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(false)
                expect(result.toSet).toEqual({})
                expect(result.toUnset).toEqual([])
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'no_change' })
                expect(mockPersonProfileIgnoredPropertiesCounter.labels).not.toHaveBeenCalled()
            })

            it('should return no changes when all properties have the same value', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { custom_prop: 'same_value' },
                    },
                } as any

                const personProperties = { custom_prop: 'same_value' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(false)
                expect(result.toSet).toEqual({})
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'no_change' })
            })

            it('should return no changes when $set_once property already exists', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set_once: { first_seen: '2024-01-01' },
                    },
                } as any

                const personProperties = { first_seen: '2023-01-01' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(false)
                expect(result.toSet).toEqual({})
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'no_change' })
            })

            it('should return no changes when trying to unset non-existent property', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $unset: ['non_existent_prop'],
                    },
                } as any

                const personProperties = { other_prop: 'value' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(false)
                expect(result.toUnset).toEqual([])
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'no_change' })
            })
        })

        describe('person events behavior', () => {
            it('should compute updates for eventToPersonProperties on $identify events', () => {
                const event: PluginEvent = {
                    event: '$identify',
                    properties: {
                        $set: { $browser: 'Chrome' },
                    },
                } as any

                const personProperties = { $browser: 'Firefox' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ $browser: 'Chrome' })
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })

            it('should compute updates for eventToPersonProperties on $set events', () => {
                const event: PluginEvent = {
                    event: '$set',
                    properties: {
                        $set: { utm_source: 'google' },
                    },
                } as any

                const personProperties = { utm_source: 'twitter' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })
        })

        describe('NO_PERSON_UPDATE_EVENTS behavior', () => {
            it('should skip updates for $exception events regardless of properties', () => {
                const event: PluginEvent = {
                    event: '$exception',
                    properties: {
                        $set: { custom_prop: 'new_value' },
                    },
                } as any

                const personProperties = { custom_prop: 'old_value' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(false)
                expect(result.toSet).toEqual({})
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'unsupported' })
            })

            it('should skip updates for $$heatmap events regardless of properties', () => {
                const event: PluginEvent = {
                    event: '$$heatmap',
                    properties: {
                        $set: { custom_prop: 'new_value' },
                    },
                } as any

                const personProperties = {}

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(false)
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'unsupported' })
            })
        })

        describe('mixed scenarios', () => {
            it('should compute updates when both custom and eventToPersonProperties change', () => {
                const event: PluginEvent = {
                    event: 'pageview',
                    properties: {
                        $set: { custom_prop: 'new_value', $browser: 'Chrome' },
                    },
                } as any

                const personProperties = { custom_prop: 'old_value', $browser: 'Firefox' }

                const result = computeEventPropertyUpdates(event, personProperties)

                expect(result.hasChanges).toBe(true)
                expect(result.toSet).toEqual({ custom_prop: 'new_value', $browser: 'Chrome' })
                expect(mockPersonProfileUpdateOutcomeCounter.labels).toHaveBeenCalledWith({ outcome: 'changed' })
            })
        })
    })

    describe('applyEventPropertyUpdates', () => {
        it('should apply property updates and return updated person', () => {
            const propertyUpdates = {
                hasChanges: true,
                toSet: { name: 'John', email: 'john@example.com' },
                toUnset: ['old_prop'],
            }

            const person = {
                id: '1',
                team_id: 123,
                uuid: 'test-uuid',
                properties: { old_prop: 'value', name: 'Jane' },
                created_at: new Date(),
                version: 0,
                is_identified: false,
            }

            const [updatedPerson, wasUpdated] = applyEventPropertyUpdates(propertyUpdates, person as any)

            expect(wasUpdated).toBe(true)
            expect(updatedPerson.properties).toEqual({ name: 'John', email: 'john@example.com' })
            expect(updatedPerson.properties.old_prop).toBeUndefined()
        })

        it('should not modify original person object', () => {
            const propertyUpdates = {
                hasChanges: true,
                toSet: { name: 'John' },
                toUnset: [],
            }

            const person = {
                id: '1',
                team_id: 123,
                uuid: 'test-uuid',
                properties: { name: 'Jane' },
                created_at: new Date(),
                version: 0,
                is_identified: false,
            }

            const [updatedPerson, _] = applyEventPropertyUpdates(propertyUpdates, person as any)

            expect(person.properties.name).toBe('Jane')
            expect(updatedPerson.properties.name).toBe('John')
            expect(person).not.toBe(updatedPerson)
        })

        it('should return false for wasUpdated when no actual changes occur', () => {
            const propertyUpdates = {
                hasChanges: false,
                toSet: { name: 'John' },
                toUnset: [],
            }

            const person = {
                id: '1',
                team_id: 123,
                uuid: 'test-uuid',
                properties: { name: 'John' },
                created_at: new Date(),
                version: 0,
                is_identified: false,
            }

            const [_, wasUpdated] = applyEventPropertyUpdates(propertyUpdates, person as any)

            expect(wasUpdated).toBe(false)
        })
    })
})
